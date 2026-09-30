import sys

import pytest

OVR = {
    "op": "add",
    "register": "overlord",
    "row": {"ID": "OVR-001", "Path": "src/a.py", "Kind": "FILE", "Purpose": "entry"},
}


def _pace(project):
    return project.write(
        [
            {
                "op": "pace",
                "nodule": {
                    "ID": "NDL-001",
                    "Name": "boot",
                    "Lane": "main",
                    "Request": "make it boot",
                    "Intent": "boot path",
                    "Exit": "boots",
                },
                "tasks": [
                    {"ID": "PAC-001", "Kind": "AREA", "Pos": "A1", "Title": "Core"},
                    {
                        "ID": "PAC-002",
                        "Kind": "PHASE",
                        "Pos": "A1.P1",
                        "Title": "Boot",
                        "Exit": "boots",
                        "Binds": "OGM-001",
                    },
                    {
                        "ID": "PAC-003",
                        "Kind": "PACE",
                        "Pos": "A1.P1.01",
                        "Title": "Load",
                        "Produce": "loader",
                        "In": "OVR-001",
                        "Out": "src/new.py",
                    },
                ],
                "requirements": [
                    {
                        "ID": "OGM-001",
                        "Title": "Boots",
                        "Authority": "USER",
                        "Origin": "make it boot",
                        "Requirement": "boots",
                        "Binds": "OVR-001",
                        "Probe": f'"{sys.executable}" -c "print(1)"',
                    }
                ],
            }
        ],
        "tester",
    )


def test_pace_add_and_ledger(project):
    project.write([OVR], "tester")
    result = _pace(project)
    assert set(result["changed_ids"]) == {"NDL-001", "PAC-001", "PAC-002", "PAC-003", "OGM-001"}
    assert result["validation"]["valid"]
    assert project.log("PAC-003", 10)[-1]["op"] == "add"
    assert "PAC-003" in [r["ID"] for r in project.store.load().tables["todo"]]


def test_status_latch_probe_and_frames(project):
    project.write([OVR], "tester")
    _pace(project)
    project.write([{"op": "status", "id": "PAC-003", "status": "ACTIVE"}], "tester")
    assert "pace=PAC-003" in project.frame("session").splitlines()[0]
    assert "OVR OVR-001 src/a.py" in project.frame("edit", "src/a.py")
    (project.root / "src" / "new.py").write_text("y = 2\n")
    touched = project.touch("src/new.py", "hook")
    assert "registered #unpurposed" in touched
    assert any(r["Path"] == "src/new.py" for r in project.store.load().tables["overlord"])
    probe = project.probe("OGM-001", "tester")
    assert probe["exit"] == 0
    rows = {r["ID"]: r for r in project.store.load().tables["organism"]}
    assert " exit:0 " in rows["OGM-001"]["Evidence"]
    project.write([{"op": "status", "id": "OGM-001", "status": "VALIDATED_COMPLETE"}], "tester")
    project.write(
        [
            {
                "op": "add",
                "register": "decision",
                "row": {
                    "ID": "DEC-001",
                    "Kind": "LATCH",
                    "Subject": "PAC-003",
                    "Question": "ship?",
                    "Authority": "USER",
                    "Latched": "false",
                },
            }
        ],
        "tester",
    )
    stop = project.stop("hook")
    assert stop["block"] and stop["open_latches"] == ["DEC-001"]
    project.write(
        [{"op": "latch", "id": "DEC-001", "latched": "true", "evidence": "user said ship"}],
        "tester",
    )
    assert project.stop("hook")["block"] is False
    assert project.q("DEC-001").startswith("DEC DEC-001 LATCH USER latched")


def test_guards(project):
    project.write([OVR], "tester")
    _pace(project)
    with pytest.raises(ValueError, match="immutable"):
        project.write([{"op": "set", "id": "PAC-003", "fields": {"Status": "DONE"}}], "tester")
    with pytest.raises(ValueError, match="Evidence required"):
        project.write([{"op": "status", "id": "OGM-001", "status": "VALIDATED_COMPLETE"}], "tester")
    with pytest.raises(ValueError, match="Unknown ID"):
        project.write(
            [{"op": "link", "id": "PAC-003", "field": "In", "target": "OVR-404"}], "tester"
        )
    with pytest.raises(ValueError, match="incomplete"):
        project.write([{"op": "absorb", "id": "NDL-001"}], "tester")
    before = project.store.load().revision
    with pytest.raises(ValueError):
        project.write(
            [
                {
                    "op": "add",
                    "register": "overlord",
                    "row": {
                        "ID": "OVR-002",
                        "Path": "src/a.py",
                        "Kind": "FILE",
                        "Purpose": "dup ok",
                    },
                },
                {"op": "status", "id": "PAC-999", "status": "DONE"},
            ],
            "tester",
        )
    assert project.store.load().revision == before
