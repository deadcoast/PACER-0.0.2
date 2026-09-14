"""Context encoding preserves meaning and refusal behavior across wire versions."""

import json

import pytest
from pacer_mcp import context
from pacer_mcp.semantics import canonical


def test_compact_context_round_trips_all_facts_and_reduces_bytes(operational):
    expanded = operational.context("PAC-001", encoding="expanded", max_bytes=100_000)
    compact = operational.context("PAC-001", max_bytes=100_000)
    restored = context.expand_context(compact)
    assert compact["encoding"] == "pacer-context/2"
    assert compact["required_bytes"] < expanded["required_bytes"]
    restored.pop("required_bytes")
    expanded.pop("required_bytes")
    assert restored == expanded
    assert compact["required_bytes"] == len(canonical(compact).encode("utf-8"))


def test_compaction_round_trips_direction_kinds_unicode_and_empty_edges():
    source = {
        "required_ids": ["PAC-001", "PAC-002", "OVR-001"],
        "relations": [
            {"source": "PAC-001", "relation": "BlockedBy:hard", "target": "PAC-002"},
            {"source": "PAC-002", "relation": "BlockedBy:optional", "target": "PAC-001"},
            {"source": "PAC-001", "relation": "OVRRefs", "target": "OVR-001"},
        ],
        "literal": ' :⡀++\nPreserve "PAC-999" and whitespace. ',
        "custom": {"n": 2.0},
    }
    for relations in (source["relations"], []):
        packet = source | {"relations": relations}
        assert context.expand_context(context.compact_context(packet)) == packet
        assert packet == source | {"relations": relations}


@pytest.mark.parametrize("bad", [-1, True, 999, "0"])
def test_decoder_rejects_invalid_edge_indexes(operational, bad):
    packet = operational.context("PAC-001")
    packet["relations"]["edges"][0][0] = bad
    with pytest.raises(ValueError, match="context"):
        context.expand_context(packet)


def test_compaction_preserves_cold_checkpoint_delta_and_receipt(operational, operate):
    operate({"op": "checkpoint", "id": "PAC-001", "next_action": "verify"})
    (operational.store.root / "settings.json").write_text('{"retries":1}', encoding="utf-8")
    small = operational.context("PAC-001")
    expanded = operational.context("PAC-001", encoding="expanded")
    assert small["delta"] == expanded["delta"]
    assert small["receipt"] == expanded["receipt"]
    assert small["delta"]["changed_sources"] == ["settings.json"]
    refusal = operational.context("PAC-001", max_bytes=256)
    assert not refusal["complete"] and refusal["receipt"] is None and refusal["tables"] == {}
    assert "context_budget" in json.dumps(refusal)
