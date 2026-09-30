import json

from pacer_mcp.gates import edit_decision, effective_tier, stop_decision
from pacer_mcp.hook import (
    edit_path,
    event_key,
    find_root,
    hook_output,
    run,
    seen_recently,
    worktree_changes,
)
from pacer_mcp.provider import NullProvider
from pacer_mcp.schema import empty_row
from pacer_mcp.spec import read_spec
from pacer_mcp.store import Store

from tests.webs import web


def test_effective_tier_inherits_and_raises(registers):
    t = web(registers)
    spec = read_spec(registers)
    pace = t["todo"][2]
    assert effective_tier(pace, t, spec) == "prototype"
    t["todo"][1]["Tier"] = "release"
    assert effective_tier(pace, t, spec) == "release"
    pace["Tier"] = "protected"
    assert effective_tier(pace, t, spec) == "protected"
    pace["Tier"] = "sketch"
    assert effective_tier(pace, t, spec) == "release"


def test_stop_matrix(registers):
    t = web(registers)
    store, spec = Store(registers), read_spec(registers)
    d = stop_decision(t, registers, store, NullProvider(), spec)
    assert d["block"] is False and d["next"] == "implement"
    t["todo"][1]["Tier"] = "integrated"
    t["organism"][0]["Evidence"] = "rev:none src:0000000 exit:1 out:0000000 at:2026-09-29T00:00:00Z"
    d = stop_decision(t, registers, store, NullProvider(), spec)
    assert d["block"] is True and "OGM-001 FAIL" in d["reasons"][0] and d["next"] == "verify"
    t["organism"][0]["Evidence"] = "rev:none src:0000000 exit:0 out:0000000 at:2026-09-29T00:00:00Z"
    d = stop_decision(t, registers, store, NullProvider(), spec)
    assert d["block"] is False  # integrated tolerates STALE
    t["todo"][1]["Tier"] = "release"
    assert stop_decision(t, registers, store, NullProvider(), spec)["block"] is True
    t["decision"].append(
        empty_row(
            "decision",
            {
                "ID": "DEC-003",
                "Kind": "LATCH",
                "Subject": "PAC-003",
                "Question": "delete old data?",
                "Authority": "USER",
                "Latched": "false",
            },
        )
    )
    d = stop_decision(t, registers, store, NullProvider(), spec)
    assert d["open_latches"] == ["DEC-003"] and d["block"] is True and d["next"] == "inspect"


def test_edit_decision_protected(registers):
    t = web(registers)
    store, spec = Store(registers), read_spec(registers)
    assert edit_decision(t, registers, store, spec, "src/b.py")["deny"] is False
    assert edit_decision(t, registers, store, spec, "src/c.py")["deny"] is True
    t["decision"].append(
        empty_row(
            "decision",
            {
                "ID": "DEC-009",
                "Kind": "LATCH",
                "Subject": "OVR-003",
                "Question": "may edit c?",
                "Chosen": "yes",
                "Authority": "USER",
                "Latched": "true",
            },
        )
    )
    assert edit_decision(t, registers, store, spec, "src/c.py")["deny"] is False


def test_hook_helpers(tmp_path):
    (tmp_path / "todo.PACER.csv").write_text("ID\n")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_root(nested) == tmp_path
    assert edit_path("Edit", {"file_path": str(tmp_path / "x.py")}, tmp_path) == "x.py"
    assert edit_path("NotebookEdit", {"notebook_path": "n.ipynb"}, tmp_path) == "n.ipynb"
    patch = "*** Begin Patch\n*** Update File: src/a.py\n@@\n-x\n+y\n*** End Patch"
    assert edit_path("apply_patch", {"command": patch}, tmp_path) == "src/a.py"
    assert edit_path("Bash", {"command": "ls"}, tmp_path) is None
    out = json.loads(hook_output("PreToolUse", "ctx", deny="no"))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    out = json.loads(hook_output("PreToolUse", "ctx"))
    assert "permissionDecision" not in out["hookSpecificOutput"]
    assert out["hookSpecificOutput"]["additionalContext"] == "ctx"
    assert hook_output("SessionStart", "ctx") == "ctx"
    assert hook_output("UserPromptSubmit", "") == ""
    assert hook_output("PostToolUse", "") == ""
    assert json.loads(hook_output("Stop", "why", block=True)) == {
        "decision": "block",
        "reason": "why",
    }
    assert hook_output("Stop", "gate text", block=False) == ""


def test_worktree_changes_lists_shell_edits(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "todo.PACER.csv").write_text("ID\n")
    (tmp_path / "ledger.PACER.jsonl").write_text("")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n")
    (tmp_path / ".pacer").mkdir()
    (tmp_path / ".pacer" / "lock").write_text("")
    assert worktree_changes(tmp_path) == ["src/a.py"]


def test_duplicate_events_are_suppressed(project):
    payload = {"cwd": str(project.root), "session_id": "s1", "source": "startup"}
    key = event_key("session-start", payload)
    assert key == event_key("session-start", dict(payload))
    assert key != event_key("session-start", {**payload, "session_id": "s2"})
    assert seen_recently(project.root, key) is False
    assert seen_recently(project.root, key) is True
    assert seen_recently(project.root, key, window=0.0) is False
    fresh = {**payload, "session_id": "s3"}
    first = run("session-start", fresh)
    second = run("session-start", fresh)
    assert first[1].startswith("PACER ") and second == (0, "")
    edit = {
        "cwd": str(project.root),
        "session_id": "s3",
        "tool_name": "Edit",
        "tool_use_id": "t1",
        "tool_input": {"file_path": str(project.root / "src" / "a.py")},
    }
    assert run("pre-edit", edit)[1] != ""
    assert run("pre-edit", edit) == (0, "")
    assert run("pre-edit", {**edit, "tool_use_id": "t2"})[1] != ""
