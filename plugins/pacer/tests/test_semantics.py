"""Operational meaning is explicit; quoted words never manufacture graph edges."""

import json

import pytest
from pacer_mcp.schema import HEADERS
from pacer_mcp.store import encode_csv


def test_history_mentions_do_not_create_operational_edges(paced, apply):
    apply({"op": "append", "id": "PAC-001", "field": "Notes", "text": "Old OVR-006 attempt"})
    graph = paced.graph("PAC-001", depth=1)
    assert "OVR-006" not in graph["ids"]
    assert {"source": "PAC-002", "relation": "BlockedBy:hard", "target": "PAC-001"} in graph[
        "relations"
    ]


@pytest.mark.parametrize(
    "fields",
    [
        {"Authority": "guessed"},
        {"Authority": "USER", "RuleType": "exec_python"},
        {
            "Authority": "USER",
            "OriginText": "preserve value",
            "RuleType": "json_ge",
            "RuleSubject": "OVR-001",
            "RuleSelector": "/count",
            "RuleValue": '"five"',
            "OVRRefs": "OVR-001",
        },
    ],
)
def test_invalid_operational_meaning_rejected_without_writes(paced, apply, fields):
    before = paced.onboard()["revision"]
    with pytest.raises(ValueError):
        apply({"op": "set", "id": "OGM-001", "fields": fields})
    assert paced.onboard()["revision"] == before


def test_original_source_text_is_literal_and_preserved(paced, apply):
    original = 'Keep "PAC-999" literally; do not reinterpret it.\nWeirdness stays.'
    apply(
        {
            "op": "set",
            "id": "OGM-001",
            "fields": {"Authority": "USER", "OriginText": original, "RuleType": "manual"},
        }
    )
    assert paced.query("organism", where={"ID": "OGM-001"}, fields=["OriginText"])["rows"] == [
        {"OriginText": original}
    ]
    assert "PAC-999" not in paced.graph("OGM-001")["ids"]


def test_profile_migration_preserves_legacy_meaning(paced):
    fields = [
        f
        for f in HEADERS["organism"]
        if f
        not in {
            "Authority",
            "OriginText",
            "RuleType",
            "RuleSubject",
            "RuleSelector",
            "RuleValue",
            "EvidenceBindings",
            "EvidenceArtifact",
        }
    ]
    with paced.store.locked():
        rows = paced.store.load().tables["organism"]
    original = rows[0]["Requirement"]
    (paced.store.root / "organism.PACER.csv").write_bytes(
        encode_csv(fields, [{f: r[f] for f in fields} for r in rows])
    )
    receipt = paced.onboard()
    paced.migrate(
        actor="tester",
        revision=receipt["revision"],
        onboarding=receipt["onboarding"],
        preview=False,
    )
    row = paced.query(
        "organism", fields=["Requirement", "Authority", "RuleType", "EvidenceBindings"]
    )["rows"][0]
    assert row == {
        "Requirement": original,
        "Authority": "LEGACY",
        "RuleType": "",
        "EvidenceBindings": "",
    }
    json.dumps(paced.onboard())
