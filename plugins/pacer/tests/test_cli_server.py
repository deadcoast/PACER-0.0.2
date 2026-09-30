import io
import json
import sys

from pacer_mcp.cli import main
from pacer_mcp.server import build_server


def test_cli_roundtrip(project, capsys):
    root = str(project.root)
    ops = project.root / "ops.json"
    ops.write_text(
        json.dumps(
            [
                {
                    "op": "add",
                    "register": "overlord",
                    "row": {
                        "ID": "OVR-001",
                        "Path": "src/a.py",
                        "Kind": "FILE",
                        "Purpose": "entry",
                    },
                }
            ]
        )
    )
    assert main(["--root", root, "write", "--file", str(ops), "--actor", "t"]) == 0
    capsys.readouterr()
    assert main(["--root", root, "q", "OVR-001"]) == 0
    assert capsys.readouterr().out.strip().startswith("OVR OVR-001 src/a.py")
    assert main(["--root", root, "frame", "session"]) == 0
    assert capsys.readouterr().out.startswith("PACER ")
    assert main(["--root", root, "validate"]) == 0
    assert main(["--root", root, "tree"]) == 0


def test_hook_subcommand_reads_stdin(project, capsys, monkeypatch):
    payload = {
        "cwd": str(project.root),
        "tool_name": "Edit",
        "tool_input": {"file_path": str(project.root / "src" / "a.py")},
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert main(["hook", "pre-edit"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "unregistered" in out["hookSpecificOutput"]["additionalContext"]
    assert "permissionDecision" not in out["hookSpecificOutput"]
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(project.root.parent)})))
    assert main(["hook", "session-start"]) == 0
    assert capsys.readouterr().out == ""


async def test_mcp_tools_list():
    server = build_server()
    names = {t.name for t in await server.list_tools()}
    assert names == {
        "pacer_frame",
        "pacer_q",
        "pacer_write",
        "pacer_probe",
        "pacer_validate",
        "pacer_initialize",
        "pacer_migrate",
        "pacer_log",
        "pacer_recover",
    }
