import json

from pacer.hook import HookState, edit_path, event_key, hook_output, run, worktree
from tests.conftest import row, tables


def test_edit_path_per_harness(root):
    assert edit_path("Edit", {"file_path": str(root / "src" / "a.py")}, root) == "src/a.py"
    assert edit_path("Write", {"file_path": "src/new.py"}, root) == "src/new.py"
    assert edit_path("NotebookEdit", {"notebook_path": "n.ipynb"}, root) == "n.ipynb"
    patch = "*** Begin Patch\n*** Update File: src/a.py\n@@\n-x\n+y\n*** End Patch"
    assert edit_path("apply_patch", {"command": patch}, root) == "src/a.py"
    assert edit_path("apply_patch", {"input": "*** Add File: docs/x.md\n+hi"}, root) == "docs/x.md"
    assert edit_path("Bash", {"command": "ls"}, root) is None
    assert edit_path("Edit", {"file_path": str(root.parent / "elsewhere.py")}, root) is None
    # PACER's own state is not source: edits there are never framed or recorded.
    assert edit_path("Edit", {"file_path": ".pacer/todo.pacer.csv"}, root) is None


def test_output_never_grants_permission_and_is_silent_when_empty():
    assert hook_output("SessionStart", "ctx") == "ctx"
    allowed = json.loads(hook_output("PreToolUse", "ctx"))["hookSpecificOutput"]
    assert allowed == {"hookEventName": "PreToolUse", "additionalContext": "ctx"}
    denied = json.loads(hook_output("PreToolUse", "ctx", deny="no"))["hookSpecificOutput"]
    assert denied["permissionDecision"] == "deny" and denied["permissionDecisionReason"] == "no"
    assert hook_output("UserPromptSubmit", "") == "" and hook_output("PostToolUse", "") == ""
    assert json.loads(hook_output("Stop", "why", block=True)) == {
        "decision": "block",
        "reason": "why",
    }
    assert hook_output("Stop", "gate text") == ""


def test_repeated_events_are_suppressed(project):
    payload = {"cwd": str(project.root), "session_id": "s1", "source": "startup"}
    key = event_key("session-start", payload)
    assert key == event_key("session-start", dict(payload))
    assert key != event_key("session-start", {**payload, "session_id": "s2"})
    state = HookState(project.root)
    assert state.seen_recently(key) is False and state.seen_recently(key) is True
    assert state.seen_recently(key, window=0.0) is False
    first = run("session-start", {**payload, "session_id": "s3"})
    assert first[1].startswith("PACER demo") and run(
        "session-start", {**payload, "session_id": "s3"}
    ) == (0, "")


def test_outside_a_governed_project_the_hook_is_silent(root):
    for event in ("session-start", "prompt", "pre-edit", "post-edit", "stop"):
        assert run(
            event, {"cwd": str(root), "tool_name": "Edit", "tool_input": {"file_path": "src/a.py"}}
        ) == (0, "")
    assert not (root / ".pacer").exists()
    assert run("nonsense", {"cwd": str(root)})[0] == 2


def test_each_event_end_to_end(seeded):
    cwd = str(seeded.root)
    assert run("session-start", {"cwd": cwd, "session_id": "a", "source": "compact"})[1].startswith(
        "PACER demo tier=prototype pace=PAC-003"
    )
    prompt = json.loads(run("prompt", {"cwd": cwd, "session_id": "a", "prompt": "fix src/b.py"})[1])
    assert prompt["hookSpecificOutput"]["additionalContext"].startswith("OVR OVR-002 src/b.py")
    assert run("prompt", {"cwd": cwd, "session_id": "a", "prompt": "hello"}) == (0, "")
    edit = {
        "cwd": cwd,
        "session_id": "a",
        "tool_name": "Edit",
        "tool_use_id": "t1",
        "tool_input": {"file_path": str(seeded.root / "src" / "a.py")},
    }
    before = json.loads(run("pre-edit", edit)[1])["hookSpecificOutput"]
    assert (
        "permissionDecision" not in before and "OVR OVR-001 src/a.py" in before["additionalContext"]
    )
    after = json.loads(run("post-edit", edit)[1])["hookSpecificOutput"]["additionalContext"]
    assert after == "pacer: touched src/a.py"
    protected = {**edit, "tool_use_id": "t2", "tool_input": {"file_path": "src/c.py"}}
    assert (
        json.loads(run("pre-edit", protected)[1])["hookSpecificOutput"]["permissionDecision"]
        == "deny"
    )
    assert run("stop", {"cwd": cwd, "session_id": "a"}) == (
        0,
        "",
    )  # nothing blocks at prototype tier
    assert row(seeded, "PAC-003")["Next"] == "integrate"


def test_a_deliberate_edit_registers_the_file_and_reports_stale_evidence(seeded):
    seeded.probe("OGM-001", "t")
    (seeded.root / "src" / "new.py").write_text("y = 1\n")
    assert (
        seeded.record(["src/new.py"], [], "hook", register_new=True)
        == "pacer: registered #unpurposed OVR-004"
    )
    assert row(seeded, "OVR-004")["Tags"] == "#unpurposed"
    assert row(seeded, "PAC-003")["In"] == "OVR-001;OVR-004"  # it was a planned output of the pace
    (seeded.root / "src" / "a.py").write_text("x = 2\n")
    assert (
        seeded.record(["src/a.py"], [], "hook", register_new=True)
        == "pacer: touched src/a.py | stale OGM-001"
    )


def test_shell_changes_are_recorded_once_and_never_register_files(seeded, git):
    git("add", "-A")
    git("commit", "-qm", "base")
    cwd = str(seeded.root)

    def bash(tool_use):
        out = run(
            "post-edit",
            {
                "cwd": cwd,
                "session_id": "b",
                "tool_name": "Bash",
                "tool_use_id": tool_use,
                "tool_input": {"command": "x"},
            },
        )[1]
        return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""

    assert bash("u0") == ""  # a clean tree says nothing
    (seeded.root / "src" / "a.py").write_text("x = 3\n")
    (seeded.root / "generated.txt").write_text("out\n")
    assert bash("u1") == "pacer: touched src/a.py | 1 changed path(s) have no asset row"
    assert bash("u2") == ""  # the same file versions are not reported twice
    assert [r["Path"] for r in tables(seeded)["overlord"]] == ["src/a.py", "src/b.py", "src/c.py"]


def test_renames_are_followed_staged_or_not(seeded, git):
    git("add", "-A")
    git("commit", "-qm", "base")
    (seeded.root / "lib").mkdir()
    git("mv", "src/a.py", "lib/a.py")  # staged: git reports the rename
    (seeded.root / "src" / "b.py").rename(
        seeded.root / "lib" / "b.py"
    )  # unstaged: paired by content
    versions, renames = worktree(seeded.root)
    assert sorted(renames) == [("src/a.py", "lib/a.py"), ("src/b.py", "lib/b.py")]
    assert not any(path.startswith(".pacer") for path in versions)
    out = run(
        "post-edit",
        {
            "cwd": str(seeded.root),
            "session_id": "c",
            "tool_name": "Bash",
            "tool_use_id": "m1",
            "tool_input": {"command": "git mv"},
        },
    )[1]
    text = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert text.startswith("pacer: followed src/a.py -> lib/a.py; src/b.py -> lib/b.py")
    assert [r["Path"] for r in tables(seeded)["overlord"]] == ["lib/a.py", "lib/b.py", "src/c.py"]
    assert seeded.validate()["warnings"] == []


def test_hook_trace_lists_payload_keys(seeded, tmp_path, monkeypatch):
    log = tmp_path / "trace.jsonl"
    monkeypatch.setenv("PACER_HOOK_LOG", str(log))
    run("session-start", {"cwd": str(seeded.root), "session_id": "z", "source": "startup"})
    entry = json.loads(log.read_text().splitlines()[0])
    assert entry["event"] == "session-start" and entry["keys"] == ["cwd", "session_id", "source"]
    assert entry["deduped"] is False and entry["out"].startswith("PACER demo")
