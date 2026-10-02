from pacer.schema import empty_row
from pacer.validation import validate_web


def web(**rows):
    result = {k: [] for k in ("todo", "overlord", "organism", "nodule", "decision")}
    for register, items in rows.items():
        result[register] = [empty_row(register, r) for r in items]
    return result


def test_seeded_project_is_valid_with_no_warnings(seeded):
    report = seeded.validate()
    assert report["valid"] and report["errors"] == [] and report["warnings"] == []


def test_cell_rules(root):
    live = web(
        todo=[
            {
                "ID": "PAC-001",
                "Kind": "PACE",
                "Pos": "A1.P1.01",
                "Title": "x|y",
                "Status": "TODO",
                "Produce": "p" * 141,
                "In": "OVR-999",
                "Tier": "huge",
                "Tags": "NotATag",
            }
        ]
    )
    errors = validate_web(live, root)["errors"]
    assert "PAC-001.Title: contains | or newline" in errors
    assert "PAC-001: Produce exceeds 140" in errors
    assert "REFUSAL: Unknown ID OVR-999" in errors
    assert "PAC-001: invalid Tier" in errors
    assert "PAC-001: invalid Tags" in errors


def test_register_rules(root):
    live = web(
        todo=[
            {
                "ID": "PAC-001",
                "Kind": "PHASE",
                "Pos": "A1.P1",
                "Title": "P",
                "Status": "ACTIVE",
                "Tier": "integrated",
            },
            {
                "ID": "PAC-002",
                "Kind": "PACE",
                "Pos": "A1.P1.01",
                "Title": "a",
                "Status": "DONE",
                "Produce": "x",
                "Needs": "PAC-003",
            },
            {
                "ID": "PAC-003",
                "Kind": "PACE",
                "Pos": "A1.P1.02",
                "Title": "b",
                "Status": "TODO",
                "Produce": "y",
                "Needs": "PAC-002",
            },
            {
                "ID": "PAC-004",
                "Kind": "PACE",
                "Pos": "A1.P1.02",
                "Title": "c",
                "Status": "TODO",
                "Produce": "z",
            },
        ],
        overlord=[
            {"ID": "OVR-001", "Path": "src/a.py", "Kind": "FILE", "Purpose": "p"},
            {"ID": "OVR-002", "Path": "src/a.py", "Kind": "FILE", "Purpose": "again"},
            {"ID": "OVR-003", "Path": "src/gone.py", "Kind": "FILE"},
            {
                "ID": "OVR-004",
                "Path": "src/b.py",
                "Symbol": "f",
                "Kind": "FUNCTION",
                "Purpose": "p",
            },
        ],
        organism=[
            {
                "ID": "OGM-001",
                "Title": "R",
                "Status": "VALIDATED_COMPLETE",
                "Authority": "INFERRED",
                "Requirement": "r",
            }
        ],
        decision=[
            {
                "ID": "DEC-001",
                "Kind": "LATCH",
                "Subject": "PAC-001",
                "Authority": "INFERRED",
                "Latched": "true",
            }
        ],
        nodule=[
            {
                "ID": "NDL-001",
                "Name": "n",
                "Status": "ACTIVE",
                "Lane": "main",
                "Request": "r",
                "Intent": "i",
                "Exit": "e",
            },
            {
                "ID": "NDL-002",
                "Name": "m",
                "Status": "ACTIVE",
                "Lane": "main",
                "Request": "r",
                "Intent": "i",
                "Exit": "e",
                "Spawned": "PAC-002",
            },
            {
                "ID": "NDL-003",
                "Name": "o",
                "Status": "ABSORBED",
                "Lane": "x",
                "Request": "r",
                "Intent": "i",
                "Exit": "e",
            },
        ],
    )
    report = validate_web(live, root)
    errors, warnings = report["errors"], report["warnings"]
    assert "PAC-001: PHASE requires Exit" in errors
    assert "REFUSAL: Blocked by PAC-003" in errors
    assert "REFUSAL: Circular dependency detected" in errors
    assert "PAC-004: Pos A1.P1.02 already held by PAC-003" in errors
    assert "OVR-002: same asset as OVR-001 (src/a.py)" in errors
    assert "OVR-004: FILE row required for src/b.py" in errors
    assert "REFUSAL: Evidence required" in errors
    assert "DEC-001: LATCH requires Authority USER" in errors
    assert "NDL-001: ACTIVE nodule requires Spawned" in errors
    assert "REFUSAL: Nodule lane occupied" in errors
    assert "NDL-003: an absorbed nodule belongs in the archive" in errors
    # A missing file and an empty purpose are observations, never blockers.
    assert "OVR-003: missing src/gone.py" in warnings and "OVR-003: #unpurposed" in warnings
    # An open pace at integrated tier should carry a probe; a finished one is history.
    assert "PAC-003: no Probe at tier integrated" in warnings
    assert not any(w.startswith("PAC-002") for w in warnings)


def test_live_web_is_closed_over_the_archive(root):
    live = web(
        todo=[
            {
                "ID": "PAC-002",
                "Kind": "PACE",
                "Pos": "A1.P1.01",
                "Title": "a",
                "Status": "TODO",
                "Produce": "x",
                "Needs": "PAC-001",
            }
        ],
        decision=[
            {"ID": "DEC-002", "Kind": "CHOICE", "Subject": "PAC-002", "Supersedes": "DEC-001"},
            {"ID": "DEC-003", "Kind": "CHOICE", "Subject": "PAC-001"},
        ],
    )
    archive = web(
        todo=[
            {
                "ID": "PAC-001",
                "Kind": "PACE",
                "Pos": "A1.P1.00",
                "Title": "old",
                "Status": "DONE",
                "Produce": "x",
            }
        ],
        decision=[{"ID": "DEC-001", "Kind": "CHOICE", "Subject": "PAC-001"}],
    )
    errors = validate_web(live, root, archive=archive)["errors"]
    assert "PAC-002.Needs: PAC-001 is archived" in errors
    assert "DEC-003.Subject: PAC-001 is archived" in errors
    assert not any("DEC-002" in e for e in errors)  # Supersedes may point into history
    duplicate = web(
        todo=[
            {
                "ID": "PAC-001",
                "Kind": "PACE",
                "Pos": "A1.P1.01",
                "Title": "a",
                "Status": "TODO",
                "Produce": "x",
            }
        ]
    )
    assert "Duplicate ID PAC-001" in validate_web(duplicate, root, archive=archive)["errors"]
