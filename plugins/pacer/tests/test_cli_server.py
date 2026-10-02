import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import pacer
from pacer.cli import main
from pacer.server import build_server
from tests.conftest import SEED

MAIN = Path(pacer.__file__).with_name("__main__.py")
TOOLS = {
    "pacer_frame",
    "pacer_q",
    "pacer_write",
    "pacer_probe",
    "pacer_validate",
    "pacer_sync",
    "pacer_log",
    "pacer_init",
    "pacer_migrate",
    "pacer_recover",
}


def cli(capsys, *args: str) -> tuple[int, str]:
    code = main(list(args))
    return code, capsys.readouterr().out


def test_cli_round_trip(root, capsys, monkeypatch):
    monkeypatch.chdir(root)
    code, out = cli(capsys, "init", "--name", "demo", "--tier", "integrated")
    assert code == 0 and json.loads(out)["valid"]
    ops = root / "ops.json"
    ops.write_text(json.dumps(SEED), encoding="utf-8")
    code, out = cli(capsys, "write", "--file", str(ops), "--actor", "me")
    assert code == 0 and "PAC-003" in json.loads(out)["changed_ids"]

    monkeypatch.chdir(root / "src")  # the root is found from any directory inside the project
    assert cli(capsys, "frame", "session")[1].startswith("PACER demo tier=integrated pace=PAC-003")
    assert cli(capsys, "q", "OGM-001")[1].startswith("OGM OGM-001 SCAFFOLD USER")
    assert cli(capsys, "q", "todo:ACTIVE")[1].count("\n") == 3
    tree = cli(capsys, "tree")[1].splitlines()
    assert tree[0] == "PACER demo tier=integrated"
    assert tree[1].startswith("PAC PAC-001 A1 ") and tree[2].startswith("  PAC PAC-002 A1.P1 ")
    assert tree[3].startswith("    PAC PAC-003 A1.P1.01 ")
    code, out = cli(capsys, "probe", "OGM-001")
    assert code == 0 and json.loads(out)["freshness"] == "CURRENT"
    assert json.loads(cli(capsys, "log", "OGM-001", "--limit", "1")[1])["op"] == "probe"
    (root / "src" / "c.py").unlink()
    assert json.loads(cli(capsys, "sync")[1]) == {"preview": True, "missing": ["OVR-003"]}
    assert json.loads(cli(capsys, "sync", "--apply")[1])["archived"] == ["OVR-003"]
    code, out = cli(capsys, "validate")
    open_paces = ("PAC-003", "PAC-004", "PAC-005")
    expected = [f"{key}: no Probe at tier integrated" for key in open_paces]
    assert code == 0 and json.loads(out)["warnings"] == expected


def test_cli_reports_refusals_and_missing_projects(root, capsys, monkeypatch):
    monkeypatch.chdir(root)
    assert main(["frame", "session"]) == 2
    assert "no .pacer/ here or above" in capsys.readouterr().err
    main(["init"])
    capsys.readouterr()
    ops = root / "bad.json"
    ops.write_text('[{"op": "status", "id": "PAC-404", "status": "DONE"}]')
    assert main(["write", "--file", str(ops), "--actor", "me"]) == 2
    assert "Unknown ID PAC-404" in capsys.readouterr().err


def test_runs_by_path_on_a_bare_interpreter(seeded):
    """Hooks start PACER by file path, isolated from any environment: no install, no dependency."""
    payload = json.dumps({"cwd": str(seeded.root), "session_id": "p", "source": "startup"})
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "VIRTUAL_ENV"))}
    done = subprocess.run(
        [sys._base_executable, "-I", "-B", str(MAIN), "hook", "session-start"],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        cwd=seeded.root,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("PACER demo tier=prototype pace=PAC-003")
    version = subprocess.run(
        [sys._base_executable, "-I", "-B", str(MAIN), "--version"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert version.stdout.strip() == f"pacer {pacer.__version__}"


def test_hook_survives_bad_input(root, monkeypatch, capsys):
    import io

    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert main(["hook", "stop"]) == 0
    assert capsys.readouterr().out == ""


async def test_server_tools_share_the_service(seeded):
    server = build_server(seeded.root)
    root = str(seeded.root)
    assert {tool.name for tool in await server.list_tools()} == TOOLS

    async def text(name, **args):
        content = await server.call_tool(name, {"root": root, **args})
        blocks = content[0] if isinstance(content, tuple) else content
        return blocks[0].text

    assert (await text("pacer_frame", kind="session")).startswith(
        "PACER demo tier=prototype pace=PAC-003"
    )
    assert (
        (await text("pacer_q", query="src/a.py")).splitlines()[1].startswith("OVR OVR-001 src/a.py")
    )
    wrote = json.loads(
        await text(
            "pacer_write",
            operations=[{"op": "repath", "from": "src/b.py", "to": "src/b2.py"}],
            actor="t",
            preview=True,
        )
    )
    assert wrote["preview"] and wrote["changed_ids"] == ["OVR-002"]
    archived = json.loads(
        await text("pacer_write", operations=[{"op": "archive", "ids": ["OVR-002"]}], actor="t")
    )
    assert archived["preview"] is False and "OVR-002" in archived["changed_ids"]
    with pytest.raises(Exception, match="extra|Extra|forbid"):
        await server.call_tool(
            "pacer_write",
            {
                "root": root,
                "operations": [{"op": "set", "id": "PAC-003", "feilds": {}}],
                "actor": "t",
            },
        )
    with pytest.raises(Exception, match="absolute"):
        await server.call_tool("pacer_validate", {"root": "relative/path"})
    with pytest.raises(Exception, match="outside this server's binding"):
        await server.call_tool("pacer_validate", {"root": str(seeded.root.parent)})


async def test_probe_over_real_stdio(seeded):
    """A probe spawned by the stdio server must not inherit the protocol pipe (it hung on Windows)."""
    env = {**os.environ, "PYTHONPATH": str(MAIN.parents[1])}
    params = StdioServerParameters(command=sys.executable, args=["-m", "pacer", "serve"], env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        assert {tool.name for tool in (await session.list_tools()).tools} == TOOLS
        result = await session.call_tool(
            "pacer_probe", {"root": str(seeded.root), "id": "OGM-001", "actor": "t"}
        )
        assert not result.isError
        assert json.loads(result.content[0].text)["freshness"] == "CURRENT"
