from pacer_mcp.spec import read_spec
from pacer_mcp.tree import render_tree

from tests.webs import web


def test_tree_view(registers):
    text = render_tree(web(registers), read_spec(registers))
    lines = text.splitlines()
    assert lines[0] == f"PACER::TODO version=3.0 project={registers.name} tier=prototype"
    assert lines[1] == 'AREA PAC-001 A1 "Core" ACTIVE'
    assert lines[2] == '  PHASE PAC-002 A1.P1 "Boot" ACTIVE prototype exit="boots"'
    assert lines[3] == '    PACE PAC-003 A1.P1.01 ACTIVE "loader" in=OVR-001 out=src/new.py'
