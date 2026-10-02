import sys
from pathlib import Path

import pytest

import pacer
from tests.conftest import PASS, archived, row, tables


def ids(service, register):
    return [r["ID"] for r in tables(service)[register]]


def test_pace_admits_scope_in_one_batch(seeded):
    assert ids(seeded, "todo") == ["PAC-001", "PAC-002", "PAC-003", "PAC-004", "PAC-005"]
    nodule = row(seeded, "NDL-001")
    assert nodule["Spawned"] == "PAC-003;PAC-004;PAC-005" and nodule["Targets"] == "OGM-001"
    assert row(seeded, "PAC-004")["Status"] == "TODO" and row(seeded, "PAC-004")["Kind"] == "PACE"
    assert row(seeded, "OGM-001")["Status"] == "SCAFFOLD"
    events = [e["op"] for e in seeded.log(None, 50)]
    assert events[0] == "init" and events.count("add") == 12 and events[-1] == "status"


def test_ids_are_assigned_when_omitted_and_never_reused(seeded):
    seeded.write(
        [
            {
                "op": "add",
                "register": "decision",
                "row": {"Kind": "CHOICE", "Subject": "PAC-005", "Chosen": "x"},
            }
        ],
        "t",
    )
    assert ids(seeded, "decision")[-1] == "DEC-003"
    seeded.write([{"op": "status", "id": "PAC-005", "status": "DONE"}], "t")
    seeded.write([{"op": "archive", "ids": ["PAC-005"]}], "t")
    assert [r["ID"] for r in archived(seeded)["decision"]] == ["DEC-003"]
    seeded.write(
        [
            {
                "op": "add",
                "register": "decision",
                "row": {"Kind": "CHOICE", "Subject": "PAC-004", "Chosen": "y"},
            }
        ],
        "t",
    )
    assert ids(seeded, "decision")[-1] == "DEC-004"  # DEC-003 is archived, its number stays taken
    with pytest.raises(ValueError, match="Duplicate ID PAC-005"):
        seeded.write(
            [
                {
                    "op": "add",
                    "register": "todo",
                    "row": {
                        "ID": "PAC-005",
                        "Kind": "PACE",
                        "Pos": "A1.P1.09",
                        "Title": "t",
                        "Produce": "p",
                    },
                }
            ],
            "t",
        )


def test_set_link_move_and_their_guards(seeded):
    seeded.write(
        [
            {"op": "set", "id": "PAC-004", "fields": {"Produce": "wire the loader"}},
            {"op": "link", "id": "PAC-004", "field": "Needs", "target": "PAC-003"},
            {"op": "move", "id": "PAC-005", "pos": "A1.P1.09"},
        ],
        "t",
    )
    assert row(seeded, "PAC-004")["Produce"] == "wire the loader"
    assert (
        row(seeded, "PAC-004")["Needs"] == "PAC-003" and row(seeded, "PAC-005")["Pos"] == "A1.P1.09"
    )
    seeded.write(
        [{"op": "link", "id": "PAC-004", "field": "Needs", "target": "PAC-003", "remove": True}],
        "t",
    )
    assert row(seeded, "PAC-004")["Needs"] == ""
    for op, message in (
        ({"op": "set", "id": "PAC-003", "fields": {"Status": "DONE"}}, "immutable"),
        ({"op": "set", "id": "OVR-001", "fields": {"Path": "src/z.py"}}, "immutable"),
        ({"op": "set", "id": "PAC-003", "fields": {"Nope": "x"}}, "unknown columns"),
        ({"op": "set", "id": "PAC-003", "fields": {"Produce": "x" * 141}}, "exceeds 140"),
        ({"op": "link", "id": "PAC-003", "field": "In", "target": "OVR-404"}, "Unknown ID OVR-404"),
        (
            {"op": "link", "id": "PAC-003", "field": "Title", "target": "OVR-001"},
            "not a reference column",
        ),
        ({"op": "move", "id": "PAC-003", "pos": "P1"}, "Invalid Pos"),
        ({"op": "frobnicate"}, "Unknown operation"),
        ({"op": "set", "id": "PAC-003"}, "Malformed set"),
    ):
        with pytest.raises(ValueError, match=message):
            seeded.write([op], "t")


def test_status_requires_dependencies_and_current_evidence(seeded):
    seeded.write([{"op": "link", "id": "PAC-004", "field": "Needs", "target": "PAC-003"}], "t")
    with pytest.raises(ValueError, match="Blocked by PAC-003"):
        seeded.write([{"op": "status", "id": "PAC-004", "status": "DONE"}], "t")
    with pytest.raises(ValueError, match="Evidence required"):
        seeded.write([{"op": "status", "id": "OGM-001", "status": "VALIDATED_COMPLETE"}], "t")
    assert seeded.probe("OGM-001", "t")["freshness"] == "CURRENT"
    seeded.write([{"op": "status", "id": "OGM-001", "status": "VALIDATED_COMPLETE"}], "t")
    (seeded.root / "src" / "a.py").write_text("x = 2\n")
    assert "STALE(src/a.py)" in seeded.q("OGM-001")


def test_latch_is_answered_once_by_the_user(seeded):
    seeded.write(
        [
            {
                "op": "add",
                "register": "decision",
                "row": {
                    "ID": "DEC-009",
                    "Kind": "LATCH",
                    "Subject": "PAC-003",
                    "Question": "ship?",
                },
            }
        ],
        "t",
    )
    assert row(seeded, "DEC-009")["Latched"] == "false"
    assert seeded.stop("hook")["open_latches"] == ["DEC-009"]
    seeded.write(
        [{"op": "latch", "id": "DEC-009", "latched": "true", "evidence": "user: ship it"}], "t"
    )
    assert row(seeded, "DEC-009")["Authority"] == "USER" and seeded.stop("hook")["block"] is False
    assert seeded.log("DEC-009", 5)[-1]["detail"]["evidence"] == "user: ship it"
    with pytest.raises(ValueError, match="latch applies"):
        seeded.write([{"op": "latch", "id": "DEC-002", "latched": "true"}], "t")


def test_absorb_checks_the_exit_then_retires_the_nodule(seeded):
    with pytest.raises(ValueError, match="PAC-003 not DONE; PAC-004 not DONE"):
        seeded.write([{"op": "absorb", "id": "NDL-001"}], "t")
    (seeded.root / "src" / "new.py").write_text("y = 1\n")
    seeded.record(["src/new.py"], [], "hook", register_new=True)
    seeded.probe("OGM-001", "t")
    done = [
        {"op": "status", "id": key, "status": "DONE"} for key in ("PAC-003", "PAC-004", "PAC-005")
    ]
    seeded.write([*done, {"op": "status", "id": "OGM-001", "status": "VALIDATED_COMPLETE"}], "t")
    seeded.write(
        [
            {
                "op": "add",
                "register": "decision",
                "row": {
                    "ID": "DEC-010",
                    "Kind": "CHOICE",
                    "Subject": "NDL-001",
                    "Chosen": "narrow scope",
                },
            }
        ],
        "t",
    )
    seeded.write([{"op": "absorb", "id": "NDL-001"}], "t")
    assert ids(seeded, "nodule") == []
    assert archived(seeded)["nodule"][0]["Status"] == "ABSORBED"
    assert [r["ID"] for r in archived(seeded)["decision"]] == [
        "DEC-010"
    ]  # it was only about the nodule
    assert row(seeded, "OGM-001")["Status"] == "VALIDATED_COMPLETE"  # requirements stand
    assert seeded.q("NDL-001").endswith("| archived")
    with pytest.raises(ValueError, match="NDL-001 is archived"):
        seeded.write([{"op": "absorb", "id": "NDL-001"}], "t")


def test_archive_takes_a_subtree_its_decisions_and_every_live_reference(seeded):
    with pytest.raises(ValueError, match="cannot archive open work PAC-003;PAC-004;PAC-005"):
        seeded.write([{"op": "archive", "ids": ["PAC-001"]}], "t")
    done = [
        {"op": "status", "id": key, "status": "DONE"} for key in ("PAC-003", "PAC-004", "PAC-005")
    ]
    seeded.write(done, "t")
    with pytest.raises(ValueError, match="closed with absorb"):
        seeded.write([{"op": "archive", "ids": ["NDL-001"]}], "t")
    seeded.write(
        [
            {
                "op": "add",
                "register": "todo",
                "row": {"ID": "PAC-006", "Kind": "AREA", "Pos": "A2", "Title": "Next"},
            },
            {
                "op": "add",
                "register": "todo",
                "row": {
                    "ID": "PAC-007",
                    "Kind": "PHASE",
                    "Pos": "A2.P1",
                    "Title": "More",
                    "Exit": "e",
                },
            },
            {
                "op": "add",
                "register": "todo",
                "row": {
                    "ID": "PAC-008",
                    "Kind": "PACE",
                    "Pos": "A2.P1.01",
                    "Title": "t",
                    "Produce": "p",
                    "Needs": "PAC-005",
                },
            },
            {
                "op": "add",
                "register": "decision",
                "row": {
                    "ID": "DEC-003",
                    "Kind": "LESSON",
                    "Subject": "PAC-004;OVR-002",
                    "Why": "both",
                },
            },
            {
                "op": "set",
                "id": "NDL-001",
                "fields": {"Spawned": "PAC-003;PAC-004;PAC-005;PAC-008"},
            },
        ],
        "t",
    )
    result = seeded.write([{"op": "archive", "ids": ["PAC-001", "OGM-001"]}], "t")
    assert ids(seeded, "todo") == ["PAC-006", "PAC-007", "PAC-008"]
    assert [r["ID"] for r in archived(seeded)["todo"]] == [
        "PAC-001",
        "PAC-002",
        "PAC-003",
        "PAC-004",
        "PAC-005",
    ]
    assert [r["ID"] for r in archived(seeded)["organism"]] == ["OGM-001"]
    assert [r["ID"] for r in archived(seeded)["decision"]] == [
        "DEC-002"
    ]  # its only subject retired
    assert row(seeded, "DEC-003")["Subject"] == "OVR-002"  # one subject still lives
    assert row(seeded, "PAC-008")["Needs"] == "" and row(seeded, "NDL-001")["Spawned"] == "PAC-008"
    assert ids(seeded, "overlord") == ["OVR-001", "OVR-002", "OVR-003"]  # assets never cascade
    assert seeded.validate()["valid"] and "DEC-002" in result["changed_ids"]
    assert seeded.log("PAC-003", 3)[-1]["op"] == "archive"


def test_repath_follows_files_and_directories(seeded):
    (seeded.root / "lib").mkdir()
    for name in ("a.py", "b.py", "c.py"):
        (seeded.root / "src" / name).rename(seeded.root / "lib" / name)
    seeded.write([{"op": "repath", "from": "src/", "to": "lib/"}], "t")
    assert [r["Path"] for r in tables(seeded)["overlord"]] == ["lib/a.py", "lib/b.py", "lib/c.py"]
    assert row(seeded, "PAC-003")["Out"] == "lib/new.py"
    assert seeded.validate()["warnings"] == []
    (seeded.root / "lib" / "a.py").rename(seeded.root / "lib" / "core.py")
    seeded.write([{"op": "repath", "from": "lib/a.py", "to": "lib/core.py"}], "t")
    assert row(seeded, "OVR-001")["Path"] == "lib/core.py"
    assert seeded.log(None, 1)[0]["detail"] == {"from": "lib/a.py", "to": "lib/core.py", "cells": 1}
    for op, message in (
        ({"op": "repath", "from": "nowhere/", "to": "lib/"}, "no row references"),
        ({"op": "repath", "from": "lib/", "to": "lib2"}, "two files, or two directories"),
        ({"op": "repath", "from": "lib/core.py", "to": "lib/b.py"}, "same asset as"),
        ({"op": "repath", "from": "lib/core.py", "to": "../x.py"}, "Unsafe"),
    ):
        with pytest.raises(ValueError, match=message):
            seeded.write([op], "t")


def test_sync_retires_assets_whose_file_is_gone(seeded):
    (seeded.root / "src" / "c.py").unlink()
    assert "OVR-003: missing src/c.py" in seeded.validate()["warnings"]
    assert "| missing" in seeded.q("OVR-003").splitlines()[0]
    assert seeded.sync("t") == {"preview": True, "missing": ["OVR-003"]}
    assert seeded.sync("t", preview=False)["archived"] == ["OVR-003"]
    assert ids(seeded, "overlord") == ["OVR-001", "OVR-002"] and row(seeded, "PAC-005")["In"] == ""
    assert seeded.sync("t", preview=False) == {"preview": False, "missing": []}


def test_batches_are_atomic_and_previews_write_nothing(seeded):
    before = seeded.validate()["revision"]
    with pytest.raises(ValueError, match="Unknown ID PAC-999"):
        seeded.write(
            [
                {"op": "set", "id": "PAC-004", "fields": {"Title": "changed"}},
                {"op": "status", "id": "PAC-999", "status": "DONE"},
            ],
            "t",
        )
    preview = seeded.write(
        [{"op": "set", "id": "PAC-004", "fields": {"Title": "changed"}}], "t", preview=True
    )
    assert preview["preview"] and preview["changed_ids"] == ["PAC-004"]
    assert seeded.validate()["revision"] == before and row(seeded, "PAC-004")["Title"] == "Wire"
    with pytest.raises(ValueError, match="actor"):
        seeded.write([{"op": "status", "id": "PAC-004", "status": "ACTIVE"}], " ")
    with pytest.raises(ValueError, match="1..200"):
        seeded.write([], "t")


def test_probe_command_is_recorded_with_its_output(seeded):
    result = seeded.probe("OGM-001", "t")
    assert result["exit"] == 0 and result["output_path"].startswith(".pacer/run/probes/OGM-001/")
    assert (seeded.root / result["output_path"]).read_text().startswith(f"$ {PASS}")
    assert result["card"].startswith("OGM OGM-001 SCAFFOLD USER | Requirement: boots")
    assert seeded.log("OGM-001", 1)[0]["op"] == "probe"
    with pytest.raises(ValueError, match="Unknown ID OGM-404"):
        seeded.probe("OGM-404", "t")


def test_a_probe_may_use_pacer_itself(seeded):
    """The command runs with the project lock released, so it can read the same project."""
    main = Path(pacer.__file__).with_name("__main__.py")
    command = f'"{sys.executable}" "{main}" --root . validate'
    seeded.write([{"op": "set", "id": "OGM-001", "fields": {"Probe": command}}], "t")
    result = seeded.probe("OGM-001", "t")
    assert result["exit"] == 0 and result["freshness"] == "CURRENT"
    assert '"valid": true' in (seeded.root / result["output_path"]).read_text()


def test_a_file_edited_while_its_probe_runs_leaves_stale_evidence(seeded):
    edit = "import pathlib; pathlib.Path('src/a.py').write_text('x = 9')"
    seeded.write(
        [{"op": "set", "id": "OGM-001", "fields": {"Probe": f'"{sys.executable}" -c "{edit}"'}}],
        "t",
    )
    result = seeded.probe("OGM-001", "t")
    assert result["exit"] == 0 and result["freshness"] == "STALE"
    with pytest.raises(ValueError, match="Evidence required"):
        seeded.write([{"op": "status", "id": "OGM-001", "status": "VALIDATED_COMPLETE"}], "t")


def test_probe_timeout_comes_from_the_project_frame(seeded):
    frame = seeded.layout.config
    frame.write_text(frame.read_text().replace("timeout = 120", "timeout = 1"))
    slow = type(seeded)(seeded.root)
    assert slow.config["probe_timeout"] == 1
    slow.write(
        [
            {
                "op": "set",
                "id": "OGM-001",
                "fields": {"Probe": f'"{sys.executable}" -c "import time; time.sleep(5)"'},
            }
        ],
        "t",
    )
    assert slow.probe("OGM-001", "t")["exit"] == 124
    frame.write_text(frame.read_text().replace("timeout = 1", "timeout = 99999"))
    assert type(seeded)(seeded.root).config["probe_timeout"] == 120  # out of range: the default
