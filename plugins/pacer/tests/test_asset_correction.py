"""Legacy asset correction must retain scope, evidence and ordinary lifecycle gates."""

import json
import subprocess
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pacer_mcp.schema import HEADERS

LEGACY = "Reviewed runtime settings;OVR-007;settings.json"


def correction(**changes):
    """A reviewed prose mapping and an exact identity normalization."""
    return {
        "op": "correct_assets",
        "id": "NDL-001",
        "expected": LEGACY,
        "replacements": {"Reviewed runtime settings": ["OVR-007"], "OVR-007": ["OVR-007"]},
        "evidence": "OBSERVED: reviewed the legacy wording against settings.json.",
        **changes,
    }


@pytest.fixture
def legacy(operational, operate):
    operate({"op": "set", "id": "NDL-001", "fields": {"NewAssets": LEGACY}})
    return operational


def test_correction_preserves_history_and_absorption_gates(legacy, operate):
    before = legacy.query("nodule", fields=HEADERS["nodule"])["rows"][0]
    preview = operate(correction(), preview=True)
    assert preview["preview"]
    assert legacy.query("nodule", fields=HEADERS["nodule"])["rows"][0] == before
    operate(correction())
    after = legacy.query("nodule", fields=HEADERS["nodule"])["rows"][0]
    assert after["NewAssets"] == "settings.json"
    for field in before.keys() - {"NewAssets", "Notes"}:
        assert after[field] == before[field]
    assert after["Notes"].startswith(before["Notes"])
    assert "tester: corrected NewAssets " in after["Notes"]
    history = json.loads(after["Notes"].rsplit("corrected NewAssets ", 1)[1])
    assert history == {
        "before": LEGACY,
        "after": "settings.json",
        "replacements": correction()["replacements"],
        "evidence": correction()["evidence"],
    }
    with pytest.raises(ValueError, match="Blocked|incomplete"):
        operate({"op": "absorb", "id": "NDL-001", "evidence": "Not yet accepted"})
    operate({"op": "verify", "id": "OGM-001", "evidence": "JSON bound checked"})
    operate(
        *[
            {
                "op": "transition",
                "id": "PAC-001",
                "status": state,
                "evidence": "Source rule verified",
            }
            for state in ("DOING", "REVIEW", "DONE")
        ]
    )
    operate({"op": "absorb", "id": "NDL-001", "evidence": "Corrected scope and rule checked"})
    archived = legacy.query("nodule", fields=HEADERS["nodule"])["rows"][0]
    assert archived["Status"] == "ABSORBED"
    assert after["Notes"] in archived["Notes"]
    with pytest.raises(ValueError, match="immutable"):
        operate(correction(expected="settings.json"))


@pytest.mark.parametrize(
    "changes",
    [
        {"expected": "stale"},
        {"evidence": " "},
        {"replacements": {}},
        {"replacements": {"Reviewed runtime settings": ["OVR-007"]}},
        {"replacements": {"Reviewed runtime settings": [], "OVR-007": ["OVR-007"]}},
        {"replacements": {"Reviewed runtime settings": "OVR-007", "OVR-007": ["OVR-007"]}},
        {"replacements": {"Reviewed runtime settings": [7], "OVR-007": ["OVR-007"]}},
        {"replacements": {"Reviewed runtime settings": ["OVR-008"], "OVR-007": ["OVR-007"]}},
        {"replacements": {"Reviewed runtime settings": ["OVR-999"], "OVR-007": ["OVR-007"]}},
        {"replacements": {"Reviewed runtime settings": ["OVR-007"], "OVR-007": ["OVR-008"]}},
        {
            "replacements": {
                "Reviewed runtime settings": ["OVR-007"],
                "OVR-007": ["OVR-007"],
                "settings.json": ["OVR-007"],
            }
        },
        {"id": "PAC-001"},
        {"extra": "field"},
    ],
)
def test_invalid_correction_is_atomic(legacy, operate, changes):
    revision = legacy.onboard()["revision"]
    with pytest.raises(ValueError):
        operate(correction(**changes))
    assert legacy.onboard()["revision"] == revision


@pytest.mark.parametrize(
    "asset", ["future.json", "future file.json", "folder/future file", "README.md"]
)
def test_literal_assets_cannot_be_reinterpreted(legacy, operate, asset):
    value = LEGACY + ";" + asset
    operate({"op": "set", "id": "NDL-001", "fields": {"NewAssets": value}})
    operation = correction(expected=value)
    operation["replacements"][asset] = ["OVR-007"]
    revision = legacy.onboard()["revision"]
    with pytest.raises(ValueError, match="literal|mapping"):
        operate(operation)
    assert legacy.onboard()["revision"] == revision
    # Unbuilt literal entries survive correction and still block absorption.
    operate(correction(expected=value))
    assert asset in legacy.query("nodule", fields=HEADERS["nodule"])["rows"][0]["NewAssets"].split(
        ";"
    )


def test_correction_requires_live_admitted_identity(legacy, operate):
    operate({"op": "set", "id": "OVR-007", "fields": {"Tags": "#dead"}})
    revision = legacy.onboard()["revision"]
    with pytest.raises(ValueError, match="live"):
        operate(correction())
    assert legacy.onboard()["revision"] == revision


def test_correction_retains_exact_symbol_and_unknown_ids_fail(legacy, operate):
    operate(
        {
            "op": "add",
            "register": "overlord",
            "row": {
                "ID": "OVR-009",
                "AssetType": "CONFIG",
                "Path": "settings.json",
                "Symbol": "retries",
                "Purpose": "Named retry setting",
                "NDLRefs": "NDL-001",
            },
        }
    )
    value = LEGACY + ";OVR-009"
    operate({"op": "set", "id": "NDL-001", "fields": {"NewAssets": value}})
    operation = correction(expected=value)
    operation["replacements"]["OVR-009"] = ["OVR-009"]
    operate(operation)
    row = legacy.query("nodule", fields=["NewAssets"])["rows"][0]
    assert row["NewAssets"] == "settings.json;settings.json:retries"
    value = row["NewAssets"] + ";OVR-999"
    revision = legacy.onboard()["revision"]
    with pytest.raises(ValueError, match="Unknown ID"):
        operate({"op": "set", "id": "NDL-001", "fields": {"NewAssets": value}})
    assert legacy.onboard()["revision"] == revision


def test_correction_does_not_relax_generic_removal_or_freshness(legacy, operate):
    with pytest.raises(ValueError, match="admitted"):
        operate({"op": "set", "id": "NDL-001", "fields": {"NewAssets": "settings.json"}})
    receipt = legacy.onboard()
    context = legacy.context("PAC-001", max_bytes=100_000)["receipt"]
    arguments = {
        "actor": "tester",
        "revision": receipt["revision"],
        "onboarding": receipt["onboarding"],
    }
    with pytest.raises(ValueError, match="context|Context"):
        legacy.apply([correction()], **arguments)
    (legacy.store.root / "settings.json").write_text('{"retries":4}', encoding="utf-8")
    with pytest.raises(ValueError, match="context|Context"):
        legacy.apply([correction()], **arguments, context=context)
    assert legacy.onboard()["revision"] == receipt["revision"]
    operate({"op": "append", "id": "PAC-001", "field": "Notes", "text": "Concurrent edit"})
    with pytest.raises(ValueError, match="revision|Revision"):
        legacy.apply([correction()], **arguments, context=context)


def test_cli_correction(legacy, tmp_path):
    receipt = legacy.onboard()
    context = legacy.context("PAC-001", max_bytes=100_000)["receipt"]
    commands, packet = tmp_path / "commands.json", tmp_path / "context.json"
    commands.write_text(json.dumps([correction()]), encoding="utf-8")
    packet.write_text(json.dumps(context), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pacer_mcp.cli",
            "--root",
            str(legacy.store.root),
            "apply",
            "--file",
            str(commands),
            "--context-file",
            str(packet),
            "--actor",
            "cli-test",
            "--revision",
            receipt["revision"],
            "--onboarding",
            receipt["onboarding"],
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["changed_ids"] == ["NDL-001"]
    assert (
        legacy.query("nodule", fields=HEADERS["nodule"])["rows"][0]["NewAssets"] == "settings.json"
    )


async def test_mcp_advertises_and_executes_correction(legacy):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "pacer_mcp.cli", "serve", "--root", str(legacy.store.root)],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            catalog = await client.list_tools()
            schema = next(t.inputSchema for t in catalog.tools if t.name == "pacer_apply")
            assert "correct_assets" in json.dumps(schema)
            receipt = legacy.onboard()
            context = legacy.context("PAC-001", max_bytes=100_000)["receipt"]
            result = await client.call_tool(
                "pacer_apply",
                {
                    "root": str(legacy.store.root),
                    "actor": "mcp-test",
                    "revision": receipt["revision"],
                    "onboarding": receipt["onboarding"],
                    "context": context,
                    "operations": [correction()],
                },
            )
            assert not result.isError, result.content
    assert (
        legacy.query("nodule", fields=HEADERS["nodule"])["rows"][0]["NewAssets"] == "settings.json"
    )
