"""Shared in-memory webs for frame, gate and tree tests."""

from pacer_mcp.schema import empty_row


def web(root):
    (root / "src").mkdir(exist_ok=True)
    for name in ("a.py", "b.py", "c.py"):
        (root / "src" / name).write_text("x=1\n")
    return {
        "todo": [
            empty_row(
                "todo",
                {
                    "ID": "PAC-001",
                    "Kind": "AREA",
                    "Pos": "A1",
                    "Title": "Core",
                    "Status": "ACTIVE",
                    "Tier": "prototype",
                },
            ),
            empty_row(
                "todo",
                {
                    "ID": "PAC-002",
                    "Kind": "PHASE",
                    "Pos": "A1.P1",
                    "Title": "Boot",
                    "Status": "ACTIVE",
                    "Tier": "prototype",
                    "Exit": "boots",
                    "Binds": "OGM-001",
                },
            ),
            empty_row(
                "todo",
                {
                    "ID": "PAC-003",
                    "Kind": "PACE",
                    "Pos": "A1.P1.01",
                    "Title": "Load",
                    "Status": "ACTIVE",
                    "Produce": "loader",
                    "In": "OVR-001",
                    "Out": "src/new.py",
                },
            ),
            empty_row(
                "todo",
                {
                    "ID": "PAC-004",
                    "Kind": "PACE",
                    "Pos": "A1.P1.02",
                    "Title": "Wire",
                    "Status": "TODO",
                    "Produce": "wiring",
                    "In": "OVR-002",
                },
            ),
            empty_row(
                "todo",
                {
                    "ID": "PAC-005",
                    "Kind": "PACE",
                    "Pos": "A1.P1.03",
                    "Title": "Far",
                    "Status": "TODO",
                    "Produce": "far away",
                    "In": "OVR-003",
                },
            ),
        ],
        "overlord": [
            empty_row(
                "overlord",
                {
                    "ID": "OVR-001",
                    "Path": "src/a.py",
                    "Kind": "FILE",
                    "Purpose": "entry",
                    "Latch": "DEC-001",
                },
            ),
            empty_row(
                "overlord",
                {"ID": "OVR-002", "Path": "src/b.py", "Kind": "FILE", "Purpose": "second"},
            ),
            empty_row(
                "overlord",
                {
                    "ID": "OVR-003",
                    "Path": "src/c.py",
                    "Kind": "FILE",
                    "Purpose": "third",
                    "Tier": "protected",
                },
            ),
        ],
        "organism": [
            empty_row(
                "organism",
                {
                    "ID": "OGM-001",
                    "Title": "Boots",
                    "Status": "SCAFFOLD",
                    "Authority": "USER",
                    "Requirement": "boots",
                    "Binds": "OVR-001",
                    "Probe": "true",
                },
            )
        ],
        "nodule": [],
        "decision": [
            empty_row(
                "decision",
                {
                    "ID": "DEC-001",
                    "Kind": "LATCH",
                    "Subject": "OVR-001",
                    "Question": "sync?",
                    "Chosen": "sync",
                    "Authority": "USER",
                    "Latched": "true",
                },
            ),
            empty_row(
                "decision",
                {
                    "ID": "DEC-002",
                    "Kind": "LESSON",
                    "Subject": "PAC-002",
                    "Why": "boot order matters",
                    "Authority": "OBSERVED",
                },
            ),
        ],
    }


class FakeProvider:
    name = "fake"

    def users(self, path):
        return ["src/main.py", "src/b.py"] if path == "src/a.py" else []

    def deps(self, path):
        return []
