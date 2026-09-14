"""A copied plugin must execute from its own source, independent of checkout layout."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PLUGIN = Path(__file__).resolve().parents[1]


async def test_copied_plugin_runs_its_own_stdio_server(project, tmp_path):
    copied = tmp_path / "copied plugin"
    shutil.copytree(
        PLUGIN,
        copied,
        ignore=shutil.ignore_patterns(
            ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "dist"
        ),
    )
    env = dict(os.environ, PYTHONPATH=str(copied / "src"))
    location = subprocess.run(
        [sys.executable, "-c", "import pacer_mcp.server; print(pacer_mcp.server.__file__)"],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert Path(location.stdout.strip()).is_relative_to(copied)
    async with stdio_client(
        StdioServerParameters(
            command=sys.executable, args=["-m", "pacer_mcp.cli", "serve"], cwd=str(copied), env=env
        )
    ) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            result = await client.call_tool("pacer_onboard", {"root": str(project.store.root)})
            assert not result.isError and result.structuredContent["root"] == str(
                project.store.root
            )


def test_manifest_skill_paths_and_versions_agree():
    import tomllib

    import yaml

    portable = json.loads((PLUGIN / "plugin.json").read_text())
    compatibility = json.loads((PLUGIN / ".codex-plugin/plugin.json").read_text())
    project = tomllib.loads((PLUGIN / "pyproject.toml").read_text())
    assert portable["name"] == compatibility["name"] == "pacer"
    assert (
        portable["version"].split("+")[0]
        == compatibility["version"].split("+")[0]
        == project["project"]["version"]
    )
    for entry in (PLUGIN / "skills").iterdir():
        markdown = (entry / "SKILL.md").read_text()
        frontmatter = yaml.safe_load(markdown.split("---", 2)[1])
        assert frontmatter["name"] == entry.name and frontmatter["description"]
        agent = yaml.safe_load((entry / "agents/openai.yaml").read_text())
        assert agent["dependencies"]["tools"][0]["value"] == "pacer"
        assert (entry / "../../references/FORMAT.md").resolve().is_file()
