from pacer_mcp.frames import edit_frame, prompt_frame, session_frame
from pacer_mcp.provider import NullProvider
from pacer_mcp.rank import rank
from pacer_mcp.spec import read_spec
from pacer_mcp.store import Store

from tests.webs import FakeProvider, web


def test_rank_orders_by_distance(registers):
    t = web(registers)
    ranked = {i: d for d, i in rank(t, NullProvider(), ["PAC-003"])}
    assert ranked["PAC-003"] == 0
    assert ranked["OVR-001"] == 1 and ranked["PAC-002"] == 1 and ranked["PAC-004"] == 1
    assert ranked["DEC-001"] == 2 and ranked["OGM-001"] == 2
    assert ranked["PAC-005"] >= 1 and ranked["OVR-003"] > ranked["OVR-001"]


def test_session_frame_has_spine_and_budget(registers):
    t = web(registers)
    store = Store(registers)
    spec = read_spec(registers)
    text = session_frame(t, registers, store, NullProvider(), spec)
    lines = text.splitlines()
    assert lines[0].startswith("PACER ") and "pace=PAC-003" in lines[0]
    assert any(line.startswith("PAC PAC-002 A1.P1 ACTIVE") for line in lines)
    assert any(line.startswith("PAC PAC-003 A1.P1.01 ACTIVE") for line in lines)
    assert any(line.startswith("DEC DEC-002 LESSON") for line in lines)
    assert any(line.startswith("OGM OGM-001") and "UNBOUND" in line for line in lines)
    spec["budgets"]["session"] = 260
    short = session_frame(t, registers, store, NullProvider(), spec)
    assert short.splitlines()[-1].startswith("+") and "pacer q PAC-003" in short


def test_edit_frame_registered_unregistered_and_offpace(registers):
    t = web(registers)
    store = Store(registers)
    spec = read_spec(registers)
    text = edit_frame(t, registers, store, FakeProvider(), spec, "src/a.py")
    assert "OVR OVR-001 src/a.py" in text and "used-by: src/b.py, src/main.py" in text
    assert "DEC DEC-001 LATCH USER latched" in text
    assert "OGM OGM-001" in text and "OFF-PACE" not in text
    off = edit_frame(t, registers, store, FakeProvider(), spec, "src/b.py")
    assert "OFF-PACE" in off
    new = edit_frame(t, registers, store, FakeProvider(), spec, "src/new.py")
    assert "OVR - src/new.py unregistered" in new and "OFF-PACE" not in new


def test_prompt_frame_only_on_mentions(registers):
    t = web(registers)
    spec = read_spec(registers)
    assert prompt_frame(t, registers, NullProvider(), spec, "hello there") == ""
    text = prompt_frame(t, registers, NullProvider(), spec, "look at OGM-001 and src/b.py")
    assert "OGM OGM-001" in text and "OVR OVR-002 src/b.py" in text
