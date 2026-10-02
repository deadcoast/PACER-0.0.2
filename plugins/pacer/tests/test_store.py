import json

import pytest

from pacer.schema import HEADERS, REGISTERS, empty_row
from pacer.store import Store, digest, encode_csv, parse_csv
from tests.conftest import archived, tables


def test_init_writes_headers_only_and_a_self_ignoring_run_directory(project):
    layout = project.layout
    for register in REGISTERS:
        columns, rows = parse_csv(layout.register(register).read_bytes(), register)
        assert columns == HEADERS[register] and rows == []
    settings = {path.name: text.splitlines()[-1] for path, text in layout.git_files().items()}
    assert settings == {".gitignore": "run/", ".gitattributes": "* -text"}
    assert all(path.read_text() == text for path, text in layout.git_files().items())
    assert b"\r" not in layout.register("todo").read_bytes()
    assert not (project.root / "archive").exists()
    assert sorted(p.name for p in project.root.iterdir()) == [".pacer", "src"]


def test_requires_a_state_directory(root):
    store = Store(root)
    with pytest.raises(ValueError, match="pacer init"), store.locked():
        pass
    assert not (root / ".pacer").exists()  # asking did not create anything


def test_csv_rejects_ragged_and_duplicate_columns():
    with pytest.raises(ValueError, match="ragged"):
        parse_csv(b"A,B\n1\n", "x")
    with pytest.raises(ValueError, match="duplicate"):
        parse_csv(b"A,A\n1,2\n", "x")
    data = encode_csv(["ID", "Title"], [{"ID": "PAC-001", "Title": 'a "quoted", cell'}])
    assert parse_csv(data, "x")[1][0]["Title"] == 'a "quoted", cell'


def test_archive_file_appears_with_its_first_row_and_then_persists(seeded):
    assert not seeded.layout.archived("todo").exists()
    seeded.write([{"op": "status", "id": "PAC-005", "status": "DONE"}], "t")
    seeded.write([{"op": "archive", "ids": ["PAC-005"]}], "t")
    assert [r["ID"] for r in archived(seeded)["todo"]] == ["PAC-005"]
    assert "PAC-005" not in [r["ID"] for r in tables(seeded)["todo"]]
    columns, rows = parse_csv(seeded.layout.archived("todo").read_bytes(), "a")
    assert columns == HEADERS["todo"] and len(rows) == 1


def test_interrupted_publication_rolls_forward(seeded):
    store, layout = seeded.store, seeded.layout
    with store.locked():
        snapshot = store.load()
        snapshot.tables["todo"][0]["Title"] = "Changed"
        after = snapshot.encode()
        before = {name: digest(data) for name, data in snapshot.files.items()}
        changes = {
            name: {
                "before": before.get(name),
                "after": digest(data),
                "data": __import__("base64").b64encode(data).decode(),
            }
            for name, data in after.items()
            if snapshot.files.get(name) != data
        }
        layout.journal.write_text(json.dumps({"version": 2, "changes": changes, "before": before}))
    with pytest.raises(ValueError, match="pacer recover"):
        seeded.frame("session")
    assert seeded.recover() == {"recovered": True, "files": ["todo.pacer.csv"]}
    assert tables(seeded)["todo"][0]["Title"] == "Changed"
    assert seeded.recover() == {"recovered": False}


def test_recovery_refuses_when_a_file_was_edited_outside(seeded):
    store, layout = seeded.store, seeded.layout
    with store.locked():
        snapshot = store.load()
        snapshot.tables["todo"][0]["Title"] = "Changed"
        data = snapshot.encode()["todo.pacer.csv"]
        journal = {
            "version": 2,
            "before": {name: digest(d) for name, d in snapshot.files.items()},
            "changes": {
                "todo.pacer.csv": {
                    "before": digest(snapshot.files["todo.pacer.csv"]),
                    "after": digest(data),
                    "data": __import__("base64").b64encode(data).decode(),
                }
            },
        }
        layout.journal.write_text(json.dumps(journal))
    with layout.register("todo").open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(ValueError, match="edited outside PACER"):
        seeded.recover()
    assert layout.journal.exists()  # kept for a human to reconcile


def test_a_write_that_fails_validation_changes_nothing(seeded):
    before = seeded.validate()["revision"]
    ledger = seeded.layout.ledger.read_bytes()
    bad = empty_row("overlord", {"ID": "OVR-009", "Path": "../escape.py", "Purpose": "p"})
    with pytest.raises(ValueError, match="Unsafe"):
        seeded.write([{"op": "add", "register": "overlord", "row": bad}], "t")
    assert seeded.validate()["revision"] == before
    assert seeded.layout.ledger.read_bytes() == ledger


def test_ledger_reads_from_the_end(project):
    for number in range(2500):
        project.store.ledger_append(
            {"actor": "t", "op": "note", "id": f"PAC-{number:04d}", "detail": {"pad": "x" * 60}}
        )
    assert project.layout.ledger.stat().st_size > 131072  # spans several read blocks
    newest = project.store.ledger_read(None, 3)
    assert [e["id"] for e in newest] == ["PAC-2497", "PAC-2498", "PAC-2499"]
    assert [e["id"] for e in project.store.ledger_read("PAC-0007", 5)] == ["PAC-0007"]
    assert project.store.ledger_read(None, 0) == []
    project.store.ledger_append(
        {"actor": "t", "op": "archive", "id": "PAC-0001", "detail": {"ids": ["DEC-0042"]}}
    )
    assert project.store.ledger_read("DEC-0042", 5)[0]["op"] == "archive"
