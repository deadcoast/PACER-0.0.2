"""The runtime's identity is held to `MIVIM.pipeline`, the hierarchy declared at the root."""

import json
import re
from pathlib import Path

import pytest

from pacer import identity

REPO = Path(__file__).resolve().parents[3]
PIPELINE = REPO / "MIVIM.pipeline"
PAIR = re.compile(r'"([^"]+)"\s*:\s*"([^"]+)"')


def test_lineage_matches_the_pipeline_file():
    if not PIPELINE.is_file():
        pytest.skip("no MIVIM.pipeline beside this copy of the plugin")
    text = PIPELINE.read_text(encoding="utf-8")
    agent = re.search(r"^\s*agent\s+(\S+)", text, flags=re.MULTILINE)
    assert agent and agent.group(1) == identity.AGENT
    names = [name for name, _ in PAIR.findall(text)]
    assert tuple(names) == identity.LINEAGE == ("MIVIM", "spec", "vigiles")
    roles = dict(PAIR.findall(text))
    assert roles["MIVIM"] == "parent_org" and roles["spec"] == "category"


def test_identity_names_agree_with_the_manifests():
    plugin = REPO / "plugins" / "pacer"
    for manifest in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
        data = json.loads((plugin / manifest).read_text(encoding="utf-8"))
        assert data["name"] == identity.PLUGIN
        assert data["repository"] == identity.REPOSITORY
        assert data["author"]["name"] == identity.ORG
    for market in (".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json"):
        data = json.loads((REPO / market).read_text(encoding="utf-8"))
        assert data["name"] == identity.MARKET
    assert f"{identity.PLUGIN}@{identity.MARKET}" == identity.PLUGIN_ID
    assert identity.ORG.lower() == identity.MARKET
