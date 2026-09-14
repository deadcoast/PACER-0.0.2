"""Persistence boundaries: reject corruption and recover interrupted publication."""

import json
import os
import subprocess
import sys

import pytest
from pacer_mcp.store import parse_csv


@pytest.mark.parametrize(
    "data", [b"ID,ID\n1,2\n", b"ID,Title\n1\n", b'ID,Title\n1,"unfinished', b"", b"ID\n\xff"]
)
def test_malformed_csv_is_never_silently_normalized(data):
    with pytest.raises(ValueError, match="Invalid CSV"):
        parse_csv(data, "input.csv")


def test_initialize_never_overwrites_partial_registers(project):
    path = project.store.root / "organism.PACER.csv"
    path.unlink()
    before = (project.store.root / "todo.PACER.csv").read_bytes()
    with pytest.raises(ValueError, match="already exist"):
        project.initialize()
    assert (project.store.root / "todo.PACER.csv").read_bytes() == before


def test_interrupted_multifile_publication_requires_recovery(paced, apply, monkeypatch):
    original = os.replace
    calls = 0

    def fail_during_publish(source, target):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("simulated interruption")
        return original(source, target)

    monkeypatch.setattr(os, "replace", fail_during_publish)
    with pytest.raises(OSError, match="simulated"):
        apply({"op": "link", "id": "PAC-001", "field": "OVRRefs", "target": "OVR-002"})
    monkeypatch.setattr(os, "replace", original)
    with pytest.raises(ValueError, match="recovery required"):
        paced.onboard()
    assert paced.recover()["recovered"]
    assert paced.validate()["valid"]
    assert not paced.recover()["recovered"]


def test_recovery_conflict_preserves_external_edit_and_journal(paced, apply, monkeypatch):
    original = os.replace

    def stop_after_journal(source, target):
        if str(target).endswith(".PACER.csv"):
            raise OSError("interrupted")
        return original(source, target)

    monkeypatch.setattr(os, "replace", stop_after_journal)
    with pytest.raises(OSError):
        apply({"op": "append", "id": "PAC-001", "field": "Notes", "text": "before failure"})
    monkeypatch.setattr(os, "replace", original)
    path = paced.store.root / "todo.PACER.csv"
    path.write_bytes(path.read_bytes() + b"\n")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Recovery conflict"):
        paced.recover()
    assert path.read_bytes() == before
    assert (paced.store.root / ".pacer/transaction.json").exists()


def test_journal_cannot_write_arbitrary_source(project):
    journal = project.store.root / ".pacer/transaction.json"
    journal.write_text(
        json.dumps(
            {"version": 1, "changes": {"README.md": {"before": None, "after": None, "data": None}}}
        )
    )
    with pytest.raises(ValueError, match="Non-register"):
        project.recover()
    assert (project.store.root / "README.md").read_text() == "Project authority"


def test_empty_register_still_requires_all_headers(project):
    (project.store.root / "todo.PACER.csv").write_text("ID\n", encoding="utf-8")
    assert not project.validate()["valid"]


def test_archive_cannot_mask_missing_root_nodule_headers(paced, apply):
    for row_id in ("PAC-001", "PAC-002"):
        apply(
            *[
                {"op": "transition", "id": row_id, "status": status, "evidence": "checked"}
                for status in ("DOING", "REVIEW", "DONE")
            ]
        )
    apply(
        {
            "op": "transition",
            "id": "OGM-001",
            "status": "VALIDATED_COMPLETE",
            "evidence": "checked",
        },
        {"op": "absorb", "id": "NDL-001", "evidence": "checked"},
    )
    (paced.store.root / "nodule.PACER.csv").write_text("ID\n", encoding="utf-8")
    assert not paced.validate()["valid"]


def test_recovery_checks_untouched_registers(paced, apply, monkeypatch):
    original = os.replace

    def stop_after_journal(source, target):
        if str(target).endswith(".PACER.csv"):
            raise OSError("interrupted")
        return original(source, target)

    monkeypatch.setattr(os, "replace", stop_after_journal)
    with pytest.raises(OSError):
        apply({"op": "append", "id": "PAC-001", "field": "Notes", "text": "pending"})
    monkeypatch.setattr(os, "replace", original)
    path = paced.store.root / "overlord.PACER.csv"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="Recovery conflict"):
        paced.recover()
    assert (paced.store.root / ".pacer/transaction.json").exists()


def test_other_process_excludes_writers_and_crash_releases_lock(project):
    child = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-c",
            "from pathlib import Path; import sys; "
            "from pacer_mcp.store import Store; "
            "exec('with Store(Path(sys.argv[1])).locked():\\n "
            'print("locked", flush=True)\\n sys.stdin.read()\')',
            str(project.store.root),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "locked"
        with pytest.raises(ValueError, match="writer busy"):
            project.onboard()
    finally:
        child.kill()
        child.communicate(timeout=10)
    assert project.validate()["valid"]
