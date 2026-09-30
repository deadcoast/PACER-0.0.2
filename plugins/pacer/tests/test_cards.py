from pacer_mcp.cards import card, parse_card
from pacer_mcp.schema import empty_row


def test_pace_card_layout_and_roundtrip():
    row = empty_row(
        "todo",
        {
            "ID": "PAC-041",
            "Kind": "PACE",
            "Pos": "A2.P3.05",
            "Status": "ACTIVE",
            "Tier": "prototype",
            "Produce": "session manager",
            "In": "OVR-012;OVR-019",
            "Out": "src/x.py:Foo",
            "Binds": "OGM-004",
            "Probe": "pytest -q",
            "Next": "implement",
        },
    )
    line = card("todo", row)
    assert line == (
        "PAC PAC-041 A2.P3.05 ACTIVE prototype | Produce: session manager | In: OVR-012;OVR-019 "
        "| Out: src/x.py:Foo | Binds: OGM-004 | Probe: pytest -q | Next: implement"
    )
    parsed = parse_card(line)
    assert parsed["ID"] == "PAC-041" and parsed["fields"]["Binds"] == "OGM-004"
    assert parsed["head"] == ["A2.P3.05", "ACTIVE", "prototype"]


def test_ovr_ogm_dec_headers_and_extras():
    ovr = empty_row(
        "overlord",
        {
            "ID": "OVR-012",
            "Path": "src/a.py",
            "Symbol": "S",
            "Kind": "CLASS",
            "Purpose": "p",
            "Tier": "integrated",
            "Latch": "DEC-003",
        },
    )
    assert (
        card("overlord", ovr, {"used-by": "src/main.py (+3)"})
        == "OVR OVR-012 src/a.py:S integrated | Purpose: p | Latch: DEC-003 | used-by: src/main.py (+3)"
    )
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
        },
    )
    assert card(
        "organism", ogm, {"Evidence": "rev:a1b2c3d exit:0 at:2026-09-20 STALE(src/a.py)"}
    ).endswith("| Evidence: rev:a1b2c3d exit:0 at:2026-09-20 STALE(src/a.py)")
    dec = empty_row(
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
    assert card("decision", dec).startswith(
        "DEC DEC-003 LATCH USER latched | Subject: OVR-012 | Chosen: keep sync"
    )


def test_empty_fields_are_omitted_and_pipe_is_escaped():
    row = empty_row(
        "nodule", {"ID": "NDL-019", "Status": "ACTIVE", "Lane": "auth", "Intent": "a/b"}
    )
    assert card("nodule", row) == "NDL NDL-019 ACTIVE lane=auth | Intent: a/b"
    assert (
        card("nodule", empty_row("nodule", {"ID": "NDL-020", "Status": "ACTIVE", "Intent": "x|y"}))
        == "NDL NDL-020 ACTIVE | Intent: x/y"
    )
