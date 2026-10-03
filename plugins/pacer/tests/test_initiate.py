"""`pacer init` with a host: registers, enrolment, the prompts, and the agent's JSON form."""

import argparse
import io
import json
import sys
from pathlib import Path

from pacer import initiate
from pacer.layout import CONFIG_NAME, STATE_DIR
from pacer.update import Source
from tests.test_update import FakeHost, write_source


class EnrollingHost(FakeHost):
    command = "claude"  # answers to the --claude flag; still called Fake on the line

    def __init__(self, root: Path, cache: Path):
        super().__init__(root, cache)
        self.enrolled_in: list[Path] = []

    def enrolled(self, project: Path) -> bool:
        return project in self.enrolled_in

    def enroll(self, project: Path) -> str:
        if project in self.enrolled_in:
            return "already enabled"
        self.enrolled_in.append(project)
        return "enabled for the project"


def namespace(**overrides) -> argparse.Namespace:
    base = dict(
        path=None, root=None, name="", tier="prototype", claude=False, codex=False, all=False
    )
    return argparse.Namespace(**{**base, **overrides})


def test_scan_project_describes_a_directory(tmp_path: Path, project):
    assert initiate.scan_project(tmp_path / "missing", tmp_path).state == "bad"
    (tmp_path / "file").write_text("x")
    assert initiate.scan_project(tmp_path / "file", tmp_path).notes == ["not a directory"]
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / ".git").mkdir()
    (plain / "CLAUDE.md").write_text("# hi")
    found = initiate.scan_project(plain, tmp_path)
    assert found.state == "good"
    assert found.notes == ["git repository", "not yet governed", "CLAUDE.md", "2 entries"]
    governed = initiate.scan_project(None, project.root)  # None: the default, nothing typed yet
    assert governed.state == "warn" and "already governed, registers are kept" in governed.notes


def test_init_enrols_a_host_and_keeps_registers(tmp_path: Path, monkeypatch, capsys):
    source = tmp_path / "source"
    write_source(source, "3.1.0")
    host = EnrollingHost(source, tmp_path / "cache")
    project = tmp_path / "app"
    project.mkdir()
    monkeypatch.setattr(initiate, "locate_source", lambda: Source(source, "checkout", "3.1.0"))
    monkeypatch.setattr(
        initiate, "present", lambda root, names: [host] if "claude" in names else []
    )

    assert initiate.init_main(namespace(path=project, claude=True)) == 0
    out = capsys.readouterr().out
    assert (project / STATE_DIR / CONFIG_NAME).is_file()
    assert host.log == ["install"] and host.enrolled_in == [project]
    assert "  ok  registers      5 registers, tier prototype" in out
    assert "  ok  Fake           pacer@mivim 3.1.0; enabled for the project" in out
    assert f"Open a session in {project}" in out

    # Again: the registers are untouched, the host is already current and enrolled.
    assert initiate.init_main(namespace(path=project, claude=True)) == 0
    out = capsys.readouterr().out
    assert "  --  registers      already governed, registers kept" in out
    assert "  ok  Fake           already enabled" in out
    assert host.log == ["install"]


def test_init_without_a_host_or_a_terminal_is_the_agent_form(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(initiate, "live_terminal", lambda: False)
    assert initiate.init_main(namespace(name="demo", tier="integrated")) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["valid"] and result["root"] == str(tmp_path.resolve())


def test_init_asks_for_what_is_missing_in_a_terminal(tmp_path: Path, monkeypatch, capsys):
    project = tmp_path / "asked"
    project.mkdir()
    asked: list[str] = []
    monkeypatch.setattr(initiate, "live_terminal", lambda: True)
    monkeypatch.setattr(initiate, "ask_path", lambda *a, **k: asked.append("path") or project)
    monkeypatch.setattr(initiate, "ask_hosts", lambda root, env=None: asked.append("hosts") or [])
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    assert initiate.init_main(namespace()) == 0
    assert asked == ["path", "hosts"] and (project / STATE_DIR / CONFIG_NAME).is_file()

    monkeypatch.setattr(initiate, "ask_path", lambda *a, **k: None)
    assert initiate.init_main(namespace()) == 1  # cancelled at the path


def test_init_refuses_without_a_source_or_a_host(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(initiate, "locate_source", lambda: None)
    assert initiate.init_main(namespace(path=tmp_path, codex=True)) == 2
    assert "source is unknown" in capsys.readouterr().err
    monkeypatch.setattr(initiate, "locate_source", lambda: Source(tmp_path, "kit", "3.1.0"))
    monkeypatch.setattr(initiate, "present", lambda root, names: [])
    assert initiate.init_main(namespace(path=tmp_path, codex=True)) == 2
    assert "codex is not on PATH" in capsys.readouterr().err
    assert initiate.init_main(namespace(path=tmp_path / "nowhere")) == 2
