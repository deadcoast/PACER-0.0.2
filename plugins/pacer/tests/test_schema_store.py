import json
from pathlib import Path

import pytest
from pacer_mcp import schema
from pacer_mcp.store import Store


def test_headers_have_five_registers_and_no_history_columns():
    assert set(schema.HEADERS) == {"todo", "overlord", "organism", "nodule", "decision"}
    for columns in schema.HEADERS.values():
        assert not {"Notes", "UpdatedAt", "ContextCheckpoint", "EvidenceBindings"} & set(columns)
    assert schema.HEADERS["todo"] == (
        "ID Kind Pos Title Status Tier Produce In Out Binds Needs Probe Exit Next Latch Tags".split()
    )
    assert schema.HEADERS["decision"][0:3] == ["ID", "Kind", "Subject"]


def test_pos_parts():
    assert schema.pos_parts("A2") == (2, None, None)
    assert schema.pos_parts("A2.P3") == (2, 3, None)
    assert schema.pos_parts("A2.P3.05") == (2, 3, 5)
    with pytest.raises(ValueError):
        schema.pos_parts("P3.05")


def test_refs_and_patterns():
    assert schema.refs("OVR-001; OGM-002 ;") == ["OVR-001", "OGM-002"]
    assert schema.ID_PATTERN.fullmatch("DEC-007")
    assert not schema.ID_PATTERN.fullmatch("dec-007")


def test_store_loads_empty_registers_and_appends_ledger(tmp_path: Path):
    for name in schema.REGISTERS:
        (tmp_path / f"{name}.PACER.csv").write_text(",".join(schema.HEADERS[name]) + "\n")
    store = Store(tmp_path)
    with store.locked():
        snap = store.load()
        assert set(snap.tables) == set(schema.REGISTERS)
        assert all(rows == [] for rows in snap.tables.values())
        store.ledger_append({"op": "add", "id": "PAC-001", "actor": "t"})
        store.ledger_append({"op": "set", "id": "PAC-002", "actor": "t"})
    lines = (tmp_path / schema.LEDGER).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["id"] == "PAC-001"
    assert "at" in json.loads(lines[0])
    assert [e["id"] for e in store.ledger_read("PAC-002", 10)] == ["PAC-002"]
    assert len(store.ledger_read(None, 1)) == 1
