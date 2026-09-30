"""Manifests, hooks and the single skill agree on version and layout."""

import hashlib
import json
import tomllib
from pathlib import Path

import yaml

PLUGIN = Path(__file__).resolve().parents[1]


def test_manifest_versions_and_environment_hash():
    portable = json.loads((PLUGIN / "plugin.json").read_text())
    compatibility = json.loads((PLUGIN / ".codex-plugin/plugin.json").read_text())
    claude = json.loads((PLUGIN / ".claude-plugin/plugin.json").read_text())
    project = tomllib.loads((PLUGIN / "pyproject.toml").read_text())
    assert portable["name"] == compatibility["name"] == claude["name"] == "pacer"
    assert portable["version"] == compatibility["version"] == claude["version"] == "3.0.0"
    assert project["project"]["version"] == "3.0.0"
    key = hashlib.sha256(portable["version"].encode()).hexdigest()[:16]
    mcp = json.loads((PLUGIN / "mcp.json").read_text())["mcpServers"]["pacer"]
    assert mcp["env"]["UV_PROJECT_ENVIRONMENT"] == "${PLUGIN_DATA}/venv-" + key
    claude_mcp = json.loads((PLUGIN / ".mcp.json").read_text())["mcpServers"]["pacer"]
    assert claude_mcp["env"]["UV_PROJECT_ENVIRONMENT"] == "${CLAUDE_PLUGIN_DATA}/venv-" + key
    assert (PLUGIN / compatibility["mcpServers"]).is_file()
    assert (PLUGIN / compatibility["hooks"]).is_file()


def test_hooks_cover_five_events_and_never_allow():
    hooks = json.loads((PLUGIN / "hooks/hooks.json").read_text())["hooks"]
    assert set(hooks) == {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"}
    for entries in hooks.values():
        for entry in entries:
            for hook in entry["hooks"]:
                assert hook["type"] == "command" and "pacer hook" in hook["command"]
                assert hook["timeout"] <= 20
    assert hooks["PreToolUse"][0]["matcher"] == "Edit|Write|NotebookEdit|apply_patch"
    assert hooks["SessionStart"][0]["matcher"] == "startup|resume|clear|compact"


def test_single_skill_with_frontmatter():
    entries = sorted(p.name for p in (PLUGIN / "skills").iterdir())
    assert entries == ["pacer"]
    markdown = (PLUGIN / "skills/pacer/SKILL.md").read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(markdown.split("---", 2)[1])
    assert frontmatter["name"] == "pacer" and frontmatter["description"]
    agent = yaml.safe_load((PLUGIN / "skills/pacer/agents/openai.yaml").read_text())
    assert agent["dependencies"]["tools"][0]["value"] == "pacer"
    assert (PLUGIN / "references/FORMAT.md").is_file()
