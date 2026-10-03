"""`pacer doctor`: every check as a row, the repairs it owns, the exit code."""

import argparse
import io
import sys
from pathlib import Path

import pytest

from pacer import doctor, home
from pacer.hosts import Copy
from pacer.identity import PLUGIN_ID
from pacer.update import Source
from tests.test_update import FakeCommand, FakeHost, write_source


def by_name(findings: list[doctor.Finding]) -> dict[str, doctor.Finding]:
    return {f.name: f for f in findings}


def test_machine_rows_name_the_tools_and_the_source(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(doctor, "refresh", lambda: "3.1.0")
    rows = by_name(doctor.machine(Source(tmp_path, "checkout", "3.1.0")))
    assert rows["uv"].state == "done" and rows["git"].state == "done"
    assert rows["python"].state == "done" and rows["python"].text.split()[0] >= "3.11"
    assert rows["source"].text == f"3.1.0 (checkout)  {tmp_path}"
    assert rows["origin"].state == "done" and rows["home"].state == "done"

    monkeypatch.setattr(doctor, "refresh", lambda: "3.2.0")
    rows = by_name(doctor.machine(Source(tmp_path, "checkout", "3.1.0")))
    assert rows["origin"].state == "warn" and rows["origin"].remedy == "pacer update"
    rows = by_name(doctor.machine(None))
    assert rows["source"].state == "fail" and "origin" not in rows
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    rows = by_name(doctor.machine(None))
    assert rows["uv"].state == "fail" and rows["git"].state == "fail" and "python" not in rows


def test_host_rows_find_what_the_doctor_can_repair(tmp_path: Path):
    source = tmp_path / "source"
    write_source(source, "3.1.0")
    host = FakeHost(source, tmp_path / "cache")
    rows = by_name(doctor.one_host(host, "3.1.0", None))
    assert rows["Fake"].state == "fail" and rows["Fake"].fix is not None
    assert rows["Fake cache"].state == "done"

    notes: list[str] = []
    assert rows["Fake"].fix(notes.append) == "pacer@mivim 3.1.0"
    assert host.log == ["install"]
    (tmp_path / "cache" / "3.0.0").mkdir()
    rows = by_name(doctor.one_host(host, "3.1.0", None))
    assert rows["Fake"].state == "done"
    assert rows["Fake cache"].state == "warn" and rows["Fake cache"].text == "stale copy: 3.0.0"
    assert rows["Fake cache"].fix(notes.append) == "removed 3.0.0"
    assert not (tmp_path / "cache" / "3.0.0").exists()

    host.installed.append(Copy(PLUGIN_ID, "mivim", "user", "3.0.0", tmp_path / "cache" / "3.0.0"))
    rows = by_name(doctor.one_host(host, "3.1.0", None))
    assert rows["Fake"].state == "fail"  # two versions installed
    assert by_name(doctor.one_host(host, "", None))["Fake"].fix is None  # no source: no repair


def test_host_rows_cover_hooks_and_the_project(tmp_path: Path, project):
    host = FakeHost(tmp_path, tmp_path / "cache")
    host.add_market()
    host.installed.append(Copy(PLUGIN_ID, "mivim", "user", "3.1.0"))
    assert "Fake project" not in by_name(doctor.one_host(host, "3.1.0", project.root))  # one scope
    host.scoped = True
    rows = by_name(doctor.one_host(host, "3.1.0", project.root))
    assert rows["Fake project"].state == "done"
    host.installed.clear()
    rows = by_name(doctor.one_host(host, "3.1.0", project.root))
    assert rows["Fake project"].state == "skip" and "pacer init" in rows["Fake project"].remedy
    host.hooks_enabled = lambda: False
    rows = by_name(doctor.one_host(host, "3.1.0", None))
    assert (
        rows["Fake hooks"].state == "warn" and "features enable hooks" in rows["Fake hooks"].remedy
    )


def test_command_rows(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    write_source(source, "3.1.0")
    command = FakeCommand(source / "plugins" / "pacer")
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    rows = by_name(doctor.command(command))
    assert rows["command"].state == "fail" and rows["command path"].state == "warn"
    assert rows["command"].fix(lambda _: None) == "pacer command installed"
    assert home.read_state()["install"]["command"]["fingerprint"] == command.fingerprint()
    rows = by_name(doctor.command(command))
    assert rows["command"].state == "done"
    assert by_name(doctor.command(None))["command"].state == "skip"


def test_project_rows(tmp_path: Path, seeded):
    assert by_name(doctor.project(tmp_path / "nowhere"))["registers"].state == "skip"
    rows = by_name(doctor.project(seeded.root))
    assert rows["registers"].state == "done" and rows["format"].state == "done"
    assert rows["tracking"].state == "skip" and rows["evidence"].state == "skip"

    seeded.probe("OGM-001", "tester")
    seeded.write([{"op": "status", "id": "OGM-001", "status": "VALIDATED_COMPLETE"}], "tester")
    assert by_name(doctor.project(seeded.root))["evidence"].text == "1 proven, all current"
    (seeded.root / "src" / "a.py").write_text("x = 2\n")
    rows = by_name(doctor.project(seeded.root))
    assert rows["evidence"].state == "warn" and rows["evidence"].remedy == "pacer probe OGM-001"

    seeded.layout.journal.write_text("{}")
    rows = by_name(doctor.project(seeded.root))
    assert rows["journal"].state == "warn" and rows["journal"].fix is not None
    with pytest.raises(RuntimeError, match="Unreadable PACER journal"):
        rows["journal"].fix(lambda _: None)


def test_doctor_main_shows_groups_and_exits_on_failures(tmp_path: Path, seeded, monkeypatch):
    source = tmp_path / "source"
    write_source(source, "3.1.0")
    host = FakeHost(source, tmp_path / "cache")
    monkeypatch.setattr(doctor, "locate_source", lambda: Source(source, "checkout", "3.1.0"))
    monkeypatch.setattr(doctor, "present_hosts", lambda root, wanted: [host])
    monkeypatch.setattr(doctor, "refresh", lambda: "3.1.0")
    monkeypatch.setattr(doctor, "Command", lambda uv, plugin_dir: FakeCommand(plugin_dir))
    monkeypatch.chdir(seeded.root)
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)

    assert doctor.doctor_main(argparse.Namespace(path=None, fix=False)) == 1
    text = out.getvalue()
    assert text.startswith("PACER doctor 3.1.0\nmachine\n")
    assert "\nhosts\n" in text and "\nproject\n" in text
    assert "  !!  Fake           not installed" in text
    assert "pacer doctor --fix repairs 2 of these" in text

    out.truncate(0), out.seek(0)
    assert doctor.doctor_main(argparse.Namespace(path=None, fix=True)) == 0
    text = out.getvalue()
    assert "PACER doctor repairs" in text and "  ok  Fake           pacer@mivim 3.1.0" in text
    assert "after repairs" in text and host.log == ["install"]
