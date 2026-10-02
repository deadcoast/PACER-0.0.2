import pytest

from pacer.cards import card, parse_card
from pacer.schema import empty_row


def test_pace_card_is_positional_and_round_trips():
    row = empty_row(
        "todo",
        {
            "ID": "PAC-041",
            "Kind": "PACE",
            "Pos": "A2.P3.05",
            "Status": "ACTIVE",
            "Tier": "prototype",
            "Title": "Session",
            "Produce": "session manager",
            "In": "OVR-012;OVR-019",
            "Out": "src/x.py:Foo",
            "Binds": "OGM-004",
            "Probe": "pytest -q",
            "Next": "implement",
        },
    )
    line = card("todo", row, {"latch": "DEC-003"})
    assert line == (
        "PAC PAC-041 A2.P3.05 ACTIVE prototype | Produce: session manager | In: OVR-012;OVR-019 "
        "| Out: src/x.py:Foo | Binds: OGM-004 | Probe: pytest -q | Next: implement | latch: DEC-003"
    )
    parsed = parse_card(line)
    assert parsed["register"] == "todo" and parsed["ID"] == "PAC-041"
    assert parsed["head"] == ["A2.P3.05", "ACTIVE", "prototype"]
    assert parsed["fields"]["Binds"] == "OGM-004" and parsed["fields"]["latch"] == "DEC-003"
    assert parsed["flags"] == []


def test_area_and_phase_keep_their_title():
    phase = empty_row(
        "todo",
        {
            "ID": "PAC-002",
            "Kind": "PHASE",
            "Pos": "A1.P1",
            "Status": "ACTIVE",
            "Title": "Boot",
            "Exit": "boots",
        },
    )
    assert card("todo", phase) == "PAC PAC-002 A1.P1 ACTIVE | Title: Boot | Exit: boots"


def test_asset_card_carries_derived_views_and_flags():
    asset = empty_row(
        "overlord",
        {
            "ID": "OVR-012",
            "Path": "src/a.py",
            "Symbol": "S",
            "Kind": "CLASS",
            "Purpose": "p",
            "Tier": "integrated",
        },
    )
    extras = {
        "bound-by": "OGM-004;OGM-007",
        "latch": "DEC-003",
        "used-by": "src/main.py (+3)",
        "OFF-PACE": "1",
        "missing": "1",
    }
    line = card("overlord", asset, extras)
    assert line == (
        "OVR OVR-012 src/a.py:S integrated | Purpose: p | bound-by: OGM-004;OGM-007 "
        "| latch: DEC-003 | used-by: src/main.py (+3) | missing | OFF-PACE"
    )
    assert parse_card(line)["flags"] == ["missing", "OFF-PACE"]
    assert card("overlord", asset) == "OVR OVR-012 src/a.py:S integrated | Purpose: p"


def test_requirement_decision_and_nodule_heads():
    ogm = empty_row(
        "organism",
        {
            "ID": "OGM-004",
            "Status": "PACED_REQUIREMENT",
            "Authority": "USER",
            "Tier": "release",
            "Requirement": "r",
            "Probe": "pytest",
            "Evidence": "rev:a1b2c3d src:1111111 exit:0 out:2222222 at:2026-09-20T00:00:00Z",
            "Binds": "OVR-012",
        },
    )
    line = card("organism", ogm, {"Evidence": "rev:a1b2c3d exit:0 at:2026-09-20 STALE(src/a.py)"})
    assert line == (
        "OGM OGM-004 PACED_REQUIREMENT USER release | Requirement: r | Probe: pytest "
        "| Evidence: rev:a1b2c3d exit:0 at:2026-09-20 STALE(src/a.py) | Binds: OVR-012"
    )
    latched = empty_row(
        "decision",
        {
            "ID": "DEC-003",
            "Kind": "LATCH",
            "Subject": "OVR-012",
            "Chosen": "keep sync",
            "Authority": "USER",
            "Latched": "true",
        },
    )
    assert (
        card("decision", latched)
        == "DEC DEC-003 LATCH USER latched | Subject: OVR-012 | Chosen: keep sync"
    )
    opened = latched | {"Latched": "false", "Chosen": "", "Question": "ship?"}
    assert (
        card("decision", opened)
        == "DEC DEC-003 LATCH USER open | Subject: OVR-012 | Question: ship?"
    )
    nodule = empty_row(
        "nodule", {"ID": "NDL-019", "Status": "ACTIVE", "Lane": "auth", "Intent": "a|b"}
    )
    assert (
        card("nodule", nodule, {"archived": "1"})
        == "NDL NDL-019 ACTIVE lane=auth | Intent: a/b | archived"
    )


def test_parse_rejects_non_cards():
    with pytest.raises(ValueError):
        parse_card("hello world")
