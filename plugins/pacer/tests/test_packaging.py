"""The shipped files agree with each other and with the runtime."""

import ast
import json
import re
import sys
import tomllib
from pathlib import Path

import pacer
from pacer import layout, schema
from pacer.cli import HOOK_EVENTS
from pacer.hook import EVENTS

PLUGIN = Path(__file__).resolve().parents[1]
SOURCE = PLUGIN / "src" / "pacer"
SKILL = PLUGIN / "skills" / "pacer"


def load(name: str) -> dict:
    return json.loads((PLUGIN / name).read_text(encoding="utf-8"))


def test_one_version_everywhere():
    project = tomllib.loads((PLUGIN / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["name"] == "pacer" and project["scripts"] == {"pacer": "pacer.cli:main"}
    versions = {
        project["version"],
        pacer.__version__,
        load(".claude-plugin/plugin.json")["version"],
        load(".codex-plugin/plugin.json")["version"],
    }
    assert len(versions) == 1 and re.fullmatch(r"\d+\.\d+\.\d+", pacer.__version__)
    # The state layout has its own version; a product release changes it only when the layout does.
    assert pacer.__version__.split(".")[0] == layout.FORMAT.split(".")[0]


def test_each_host_has_one_manifest_describing_the_same_plugin():
    claude, codex = load(".claude-plugin/plugin.json"), load(".codex-plugin/plugin.json")
    assert {k: codex[k] for k in claude} == claude
    assert codex["hooks"] == "./hooks/hooks.json" and codex["skills"] == "./skills/"
    assert codex["mcpServers"] == "./.codex-plugin/mcp.json"
    # Measured on Codex 0.160: a root plugin.json makes Codex skip the plugin's hooks, and
    # without one it does not substitute ${PLUGIN_ROOT}. See docs/trials/baseline-3.0.0.md.
    for stale in ("plugin.json", "mcp.json", "codex.mcp.json", "references"):
        assert not (PLUGIN / stale).exists(), stale


def test_mcp_server_per_host():
    claude = load(".mcp.json")["mcpServers"]["pacer"]
    assert claude["command"] == "uv"
    assert claude["args"] == [
        "run",
        "--locked",
        "--no-dev",
        "--project",
        "${CLAUDE_PLUGIN_ROOT}",
        "pacer",
        "serve",
    ]
    # The environment lives in the host's data directory, so it survives plugin updates.
    assert claude["env"]["UV_PROJECT_ENVIRONMENT"] == "${CLAUDE_PLUGIN_DATA}/venv"
    codex = load(".codex-plugin/mcp.json")["mcpServers"]["pacer"]
    # Codex resolves `cwd` against the plugin root and expands nothing else.
    assert codex == {
        "command": "uv",
        "args": ["run", "--locked", "--no-dev", "pacer", "serve"],
        "env": {"UV_PYTHON_DOWNLOADS": "never"},
        "cwd": ".",
    }
    assert "$" not in json.dumps(codex)
    assert claude["env"]["UV_PYTHON_DOWNLOADS"] == "never"


def test_hooks_start_the_runtime_by_path_for_every_event():
    hooks = load("hooks/hooks.json")["hooks"]
    assert set(hooks) == set(EVENTS.values())
    seen = set()
    for groups in hooks.values():
        for group in groups:
            for hook in group["hooks"]:
                unix, windows = hook["command"], hook["commandWindows"]
                assert unix.startswith(
                    'uv run --no-project --no-python-downloads --python ">=3.11" '
                )
                assert '"${CLAUDE_PLUGIN_ROOT}/src/pacer/__main__.py"' in unix
                # Codex hands hooks to PowerShell on Windows and substitutes nothing itself.
                assert windows == unix.replace("${CLAUDE_PLUGIN_ROOT}", "$env:PLUGIN_ROOT")
                assert 5 <= hook["timeout"] <= 30
                seen.add(unix.rsplit(" ", 1)[1])
    assert seen == set(HOOK_EVENTS) == set(EVENTS)
    matcher = hooks["PreToolUse"][0]["matcher"]
    assert matcher == "Edit|Write|NotebookEdit|apply_patch"
    assert hooks["PostToolUse"][0]["matcher"] == matcher + "|Bash"


def test_only_the_server_needs_a_dependency():
    """Hooks run on a bare interpreter, so nothing they import may leave the standard library."""
    allowed = set(sys.stdlib_module_names) | {"pacer"}
    for path in SOURCE.rglob("*.py"):
        if path.name in {"server.py", "models.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            for name in names:
                assert name.split(".")[0] in allowed, f"{path.name} imports {name}"


def test_no_name_from_an_earlier_layout_ships():
    legacy = re.compile(r"pacer_mcp|PACER\.csv|PACER\.jsonl|pacer_initialize|venv-[0-9a-f]{8}")
    for path in PLUGIN.rglob("*"):
        skip = {".venv", "__pycache__", "tests", "migrate"} & set(path.relative_to(PLUGIN).parts)
        if not path.is_file() or skip or path.name == "uv.lock":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        assert not legacy.search(text), f"{path.relative_to(PLUGIN)} mentions an earlier name"
        if path.suffix != ".py":
            assert ".MIVIM.spec" not in text or path.name == "format.md", path.name


def test_format_reference_lists_the_real_columns_and_limits():
    text = (SKILL / "references" / "format.md").read_text(encoding="utf-8")
    assert f"# PACER format {layout.FORMAT}" in text
    for register in schema.REGISTERS:
        section = text.split(f"### {register} ")[1].split("\n### ")[0].split("\n## ")[0]
        columns = re.findall(r"^\| ([A-Z][A-Za-z]+) \|", section, flags=re.MULTILINE)
        columns.remove("Column")  # the table's own header row
        assert columns == schema.HEADERS[register], register
        for column in columns:
            if column in schema.LIMITS:
                assert re.search(
                    rf"^\| {column} \|[^\n]*\| {schema.LIMITS[column]} \|",
                    section,
                    flags=re.MULTILINE,
                ), column
    for name in (
        layout.CONFIG_NAME,
        layout.LEDGER_NAME,
        *(layout.register_name(r) for r in schema.REGISTERS),
    ):
        assert name in text


def test_skill_names_every_operation_and_no_other():
    from pacer.commands import Editor

    operations = {name[3:] for name in dir(Editor) if name.startswith("op_")} - {"touch"}
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    listed = set(re.findall(r"^\| `([a-z]+)` \|", skill, flags=re.MULTILINE))
    assert listed == operations
    reference = (SKILL / "references" / "format.md").read_text(encoding="utf-8")
    section = reference.split("## 10. Operations")[1].split("\n## ")[0]
    assert set(re.findall(r"^\| `([a-z]+)` \|", section, flags=re.MULTILINE)) == operations
    front = skill.split("---")[1]
    assert "name: pacer" in front and "description:" in front
