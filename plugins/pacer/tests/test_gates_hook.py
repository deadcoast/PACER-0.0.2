import json

from pacer_mcp.gates import edit_decision, effective_tier, stop_decision
from pacer_mcp.hook import edit_path, find_root, hook_output
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
    assert json.loads(hook_output("Stop", "why", block=True)) == {
        "decision": "block",
        "reason": "why",
    }
