from pacer_mcp.schema import empty_row
from pacer_mcp.validation import validate_web


def tables(**rows):
    result = {k: [] for k in ("todo", "overlord", "organism", "nodule", "decision")}
    for register, items in rows.items():
        result[register] = [empty_row(register, r) for r in items]
    return result


def test_valid_minimal_web(registers):
    (registers / "src").mkdir()
    (registers / "src" / "a.py").write_text("x = 1\n")
    web = tables(
        todo=[
            {"ID": "PAC-001", "Kind": "AREA", "Pos": "A1", "Title": "Core", "Status": "ACTIVE", "Tier": "prototype"},
            {"ID": "PAC-002", "Kind": "PHASE", "Pos": "A1.P1", "Title": "Boot", "Status": "ACTIVE", "Tier": "prototype", "Exit": "boots", "Binds": "OGM-001"},
            {"ID": "PAC-003", "Kind": "PACE", "Pos": "A1.P1.01", "Title": "Load", "Status": "TODO", "Produce": "loader", "In": "OVR-001"},
        ],
        overlord=[{"ID": "OVR-001", "Path": "src/a.py", "Kind": "FILE", "Purpose": "entry"}],
        organism=[{"ID": "OGM-001", "Title": "Boots", "Status": "SCAFFOLD", "Authority": "USER", "Origin": "it must boot", "Requirement": "boots", "Binds": "OVR-001"}],
        decision=[{"ID": "DEC-001", "Kind": "LATCH", "Subject": "OVR-001", "Question": "sync?", "Chosen": "sync", "Authority": "USER", "Latched": "true"}],
    )
    report = validate_web(web, registers)
    assert report["errors"] == []


def test_rejects_pipe_limit_badref_and_tier(registers):
    web = tables(
        todo=[{"ID": "PAC-001", "Kind": "PACE", "Pos": "A1.P1.01", "Title": "x|y", "Status": "TODO", "Produce": "p" * 141, "In": "OVR-999", "Tier": "huge"}],
    )
    errors = validate_web(web, registers)["errors"]
    assert any("contains |" in e for e in errors)
    assert any("Produce exceeds 140" in e for e in errors)
    assert any("Unknown ID OVR-999" in e for e in errors)
    assert any("invalid Tier" in e for e in errors)


def test_rules_per_register(registers):
    web = tables(
        todo=[
            {"ID": "PAC-001", "Kind": "PHASE", "Pos": "A1.P1", "Title": "P", "Status": "ACTIVE", "Tier": "integrated"},
            {"ID": "PAC-002", "Kind": "PACE", "Pos": "A1.P1.01", "Title": "a", "Status": "DONE", "Produce": "x", "Needs": "PAC-003"},
            {"ID": "PAC-003", "Kind": "PACE", "Pos": "A1.P1.02", "Title": "b", "Status": "TODO", "Produce": "y", "Needs": "PAC-002"},
        ],
        organism=[{"ID": "OGM-001", "Title": "R", "Status": "VALIDATED_COMPLETE", "Authority": "INFERRED", "Requirement": "r", "Evidence": ""}],
        decision=[{"ID": "DEC-001", "Kind": "LATCH", "Subject": "PAC-001", "Question": "q", "Chosen": "c", "Authority": "INFERRED", "Latched": "true"}],
        nodule=[
            {"ID": "NDL-001", "Name": "n", "Status": "ACTIVE", "Lane": "main", "Request": "do it", "Intent": "i", "Exit": "e"},
            {"ID": "NDL-002", "Name": "m", "Status": "ACTIVE", "Lane": "main", "Request": "again", "Intent": "i", "Exit": "e", "Spawned": "PAC-002"},
        ],
    )
    errors = validate_web(web, registers)["errors"]
    assert "PAC-001: PHASE requires Exit" in errors
    assert "PAC-002: Probe required at tier integrated" in errors
    assert "REFUSAL: Blocked by PAC-003" in errors
    assert "REFUSAL: Circular dependency detected" in errors
    assert "REFUSAL: Evidence required" in errors
    assert "DEC-001: LATCH requires Authority USER" in errors
    assert "NDL-001: ACTIVE nodule requires Spawned" in errors
    assert "REFUSAL: Nodule lane occupied" in errors
