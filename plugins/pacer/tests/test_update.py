import argparse
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pacer import home, update
from pacer.display import Journey
from pacer.hook import run
from pacer.hosts import Command, Copy, Host, differences, digests, in_use
from pacer.identity import PLUGIN_ID

STUB_INSTALLER = """\
import json, sys
emit = lambda **e: print(json.dumps({"journey": 1, **e}), flush=True)
emit(event="plan", steps=[{"id": "claude", "label": "Claude Code", "expect": 1.0}])
emit(event="begin", id="claude", note="comparing")
emit(event="end", id="claude", state="done", text="pacer@mivim VERSION")
emit(event="close", headline="ready in 0.4s", hints=["Start a new session to load it."], ok=True)
"""


def sh(*args: str, cwd: Path) -> str:
    base = [
        "git",
        "-c",
        "user.email=t@example.com",
        "-c",
        "user.name=t",
        "-c",
        "core.autocrlf=false",
    ]
    done = subprocess.run([*base, *args], cwd=cwd, capture_output=True, text=True, check=True)
    return done.stdout.strip()


def write_source(root: Path, version: str) -> None:
    (root / "plugins" / "pacer").mkdir(parents=True, exist_ok=True)
    (root / "plugins" / "pacer" / "pyproject.toml").write_text(
        f'[project]\nname = "pacer"\nversion = "{version}"\nrequires-python = ">=3.11"\ndependencies = ["mcp"]\n'
    )
    (root / "install.py").write_text(STUB_INSTALLER.replace("VERSION", version))
    (root / ".claude-plugin").mkdir(exist_ok=True)
    (root / ".claude-plugin" / "marketplace.json").write_text(
        '{"name": "mivim", "plugins": [{"name": "pacer"}]}'
    )


@pytest.fixture
def origin(tmp_path):
    """A bare origin tagged v3.0.0 and v3.1.0, and a checkout left at v3.0.0 on `main`."""
    bare, work, checkout = tmp_path / "origin.git", tmp_path / "work", tmp_path / "checkout"
    sh("init", "--bare", "-q", str(bare), cwd=tmp_path)
    work.mkdir()
    sh("init", "-q", "-b", "main", cwd=work)
    write_source(work, "3.0.0")
    sh("add", "-A", cwd=work)
    sh("commit", "-qm", "3.0.0", cwd=work)
    sh("tag", "-a", "v3.0.0", "-m", "v3.0.0", cwd=work)
    write_source(work, "3.1.0")
    sh("commit", "-qam", "3.1.0", cwd=work)
    sh("tag", "-a", "v3.1.0", "-m", "v3.1.0", cwd=work)
    sh("remote", "add", "origin", str(bare), cwd=work)
    sh("push", "-q", "--follow-tags", "origin", "main", cwd=work)
    sh("clone", "-q", str(bare), str(checkout), cwd=tmp_path)
    sh("reset", "-q", "--hard", "v3.0.0", cwd=checkout)
    return bare, checkout


def test_versions_are_read_from_tags(origin):
    bare, checkout = origin
    assert update.remote_versions(checkout) == ["3.0.0", "3.1.0"]
    assert update.remote_versions(str(bare)) == ["3.0.0", "3.1.0"]
    assert update.remote_versions(str(bare.parent / "nowhere.git")) == []
    assert update.parse("3.10.2") == (3, 10, 2) and update.parse("v3") is None
    assert (
        update.newer("3.1.0", "3.0.0")
        and not update.newer("3.0.0", "3.0.0")
        and not update.newer(None, "1")
    )


def test_source_is_described_and_located(origin, monkeypatch):
    _, checkout = origin
    source = update.describe(checkout)
    assert (source.kind, source.version) == ("checkout", "3.0.0")
    assert update.locate_source() is None or update.locate_source().root != checkout
    home.update_state(lambda s: s.setdefault("install", {}).__setitem__("source", str(checkout)))
    assert update.locate_source().root == checkout
    assert update.origin(source).endswith("origin.git")


def test_a_checkout_on_a_branch_fast_forwards(origin):
    _, checkout = origin
    notes = []
    state, text, root = update.advance(update.describe(checkout), "3.1.0", notes.append)
    assert (
        state == "done"
        and text.startswith("fast-forward")
        and text.endswith("1 commit(s)")
        and root == checkout
    )
    assert update.source_version(checkout) == "3.1.0" and "fetching origin" in notes
    state, text, _ = update.advance(update.describe(checkout), "3.1.0", notes.append)
    assert (state, text) == ("skip", "main current")


def test_local_work_is_never_overwritten(origin):
    _, checkout = origin
    (checkout / "mine.txt").write_text("local\n")
    sh("add", "mine.txt", cwd=checkout)
    sh("commit", "-qm", "local", cwd=checkout)
    state, text, _ = update.advance(update.describe(checkout), "3.1.0", lambda _: None)
    assert state == "skip" and "diverged" in text and "local work kept" in text
    assert update.source_version(checkout) == "3.0.0"


def test_a_kit_becomes_a_managed_clone(origin, tmp_path, monkeypatch):
    bare, _ = origin
    kit = tmp_path / "kit"
    write_source(kit, "3.0.0")
    home.update_state(lambda s: s.setdefault("install", {}).__setitem__("origin", str(bare)))
    state, text, root = update.advance(update.describe(kit), "3.1.0", lambda _: None)
    assert (
        state == "done" and root == update.managed_dir() and update.source_version(root) == "3.1.0"
    )
    assert update.describe(root).kind == "managed"
    assert sh("describe", "--tags", "--exact-match", cwd=root) == "v3.1.0"
    state, text, _ = update.advance(update.describe(root), "3.1.0", lambda _: None)
    assert (state, text) == ("skip", "v3.1.0 current")
    state, text, _ = update.advance(update.describe(kit), "3.0.0", lambda _: None)
    assert state == "skip" and "no newer release" in text


def test_notice_is_said_once_per_version_and_never_when_silenced(monkeypatch):
    monkeypatch.delenv("PACER_NO_UPDATE_CHECK")
    assert update.take_notice("3.0.0") is None
    home.update_state(lambda s: s.setdefault("update", {}).__setitem__("latest", "3.1.0"))
    assert update.session_notice("3.0.0").startswith("PACER 3.1.0 is available")
    assert update.session_notice("3.0.0") == ""  # said once
    home.update_state(lambda s: s["update"].__setitem__("latest", "3.2.0"))
    assert update.take_notice("3.0.0") == "3.2.0"  # a newer version is a new notice
    assert update.take_notice("3.2.0") is None  # nothing newer than what runs
    home.update_state(lambda s: s["update"].__setitem__("latest", "3.3.0"))
    update.set_notify(False)
    assert update.silenced() and update.take_notice("3.0.0") is None
    update.set_notify(True)
    assert update.take_notice("3.0.0") == "3.3.0"
    monkeypatch.setenv("PACER_NO_UPDATE_CHECK", "1")
    home.update_state(lambda s: s["update"].__setitem__("latest", "3.4.0"))
    assert update.take_notice("3.0.0") is None


def test_the_terminal_notice_goes_to_a_tty_only(monkeypatch):
    monkeypatch.delenv("PACER_NO_UPDATE_CHECK")
    home.update_state(lambda s: s.setdefault("update", {}).__setitem__("latest", "3.1.0"))
    quiet = io.StringIO()
    update.cli_notice(quiet, "3.0.0")
    assert quiet.getvalue() == ""

    class Tty(io.StringIO):
        encoding = "utf-8"

        def isatty(self):
            return True

    loud = Tty()
    update.cli_notice(loud, "3.0.0")
    assert (
        "PACER 3.1.0 is available" in loud.getvalue()
        and "pacer update --notify off" in loud.getvalue()
    )
    again = Tty()
    update.cli_notice(again, "3.0.0")
    assert again.getvalue() == ""


def test_the_background_check_is_claimed_once_a_day(monkeypatch):
    monkeypatch.delenv("PACER_NO_UPDATE_CHECK")
    spawned = []
    monkeypatch.setattr(update, "spawn_refresh", lambda: spawned.append(1) or True)
    day = float(update.CHECK_EVERY)
    assert update.maybe_refresh(now=2 * day) is True
    assert update.maybe_refresh(now=2 * day + 3600) is False  # claimed
    assert update.maybe_refresh(now=3 * day + 1) is True
    assert len(spawned) == 2
    update.set_notify(False)
    assert update.maybe_refresh(now=10**9) is False and len(spawned) == 2


def test_refresh_records_the_latest_from_the_origin(origin):
    bare, checkout = origin
    home.update_state(lambda s: s.setdefault("install", {}).__setitem__("source", str(checkout)))
    assert update.refresh() == "3.1.0"
    state = home.read_state()["update"]
    assert state["latest"] == "3.1.0" and state["checked_at"] > 0


def test_session_start_carries_the_notice_to_the_person(seeded, monkeypatch):
    monkeypatch.delenv("PACER_NO_UPDATE_CHECK")
    payload = {"cwd": str(seeded.root), "session_id": "n", "source": "startup"}
    assert run("session-start", payload)[1].startswith("PACER demo")  # nothing to say: plain frame
    home.update_state(
        lambda s: s.setdefault("update", {"checked_at": 10**12}).__setitem__("latest", "9.9.9")
    )
    code, out = run("session-start", {**payload, "session_id": "n2"})
    data = json.loads(out)
    assert data["hookSpecificOutput"]["additionalContext"].startswith("PACER demo")
    assert data["systemMessage"].startswith("PACER 9.9.9 is available")
    assert "pacer update --notify off" in data["systemMessage"]
    assert run("session-start", {**payload, "session_id": "n3"})[1].startswith("PACER demo")  # once


class FakeHost(Host):
    name, command = "Fake", "fake"

    def __init__(self, root: Path, cache: Path):
        super().__init__("fake", root)
        self.cache = cache
        self.market: dict[str, str] = {}
        self.installed: list[Copy] = []
        self.log: list[str] = []

    def markets(self):
        return dict(self.market)

    def copies(self):
        return list(self.installed)

    def uninstall(self, copy, *, keep_data):
        self.log.append(f"uninstall {copy.plugin_id}")
        self.installed = [c for c in self.installed if c is not copy]

    def add_market(self):
        self.market["mivim"] = str(self.root)

    def add_plugin(self):
        import shutil

        version = update.source_version(self.root)
        target = self.cache / version
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(self.root / "plugins" / "pacer", target)
        self.installed.append(Copy(PLUGIN_ID, "mivim", "user", version, target))
        self.log.append("install")

    def cache_root(self):
        return self.cache

    def run(self, *args):
        if args[:3] == ("plugin", "marketplace", "remove"):
            self.market.pop(args[3], None)
            return ""
        raise AssertionError(args)


class FakeCommand(Command):
    def __init__(self, plugin_dir):
        super().__init__("uv", plugin_dir)
        self.tools = {}
        self.installs = 0

    def listed(self):
        return dict(self.tools)

    def sync(self, record, note, *, force=False):
        state, text, kept = "skip", "pacer command current", record
        current, _ = self.status(record)
        if not current or force:
            self.installs += 1
            self.tools["pacer"] = "pacer v3.1.0"
            state, text, kept = (
                "done",
                "pacer command installed",
                {"source": str(self.plugin_dir), "fingerprint": self.fingerprint()},
            )
        return state, text, kept


def test_sync_installs_only_what_differs(tmp_path):
    root = tmp_path / "source"
    write_source(root, "3.1.0")
    host = FakeHost(root, tmp_path / "cache")
    command = FakeCommand(root / "plugins" / "pacer")
    out = io.StringIO()
    journey = Journey("install", stream=out, env={})
    with journey:
        changed, advice = update.sync(root, journey, [host], command)
        journey.close("ready" if changed else "current")
    assert changed and host.log == ["install"] and command.installs == 1
    assert [s.state for s in journey.steps] == ["done", "done"]
    assert home.read_state()["install"]["version"] == "3.1.0"
    assert home.read_state()["install"]["command"]["fingerprint"] == command.fingerprint()

    journey = Journey("install", stream=io.StringIO(), env={})
    with journey:
        changed, _ = update.sync(root, journey, [host], command)
    assert (
        not changed
        and host.log == ["install"]
        and [s.state for s in journey.steps] == ["skip", "skip"]
    )

    (root / "plugins" / "pacer" / "extra.py").write_text("x = 1\n")
    current, notes, differs = host.status("3.1.0")
    assert not current and differs == ["extra.py"] and any("differs" in n for n in notes)
    journey = Journey("install", stream=io.StringIO(), env={})
    with journey:
        changed, _ = update.sync(root, journey, [host], command)
    assert changed and host.log == ["install", "uninstall pacer@mivim", "install"]
    assert journey.steps[0].text == "pacer@mivim 3.1.0, 1 file(s) refreshed"

    journey = Journey("install", stream=io.StringIO(), env={})
    with journey:
        update.sync(root, journey, [host], command, force=True)
    assert host.log[-1] == "install" and command.installs == 2


def test_digests_skip_caches_and_name_what_changed(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for base in (a, b):
        (base / "src").mkdir(parents=True)
        (base / "src" / "x.py").write_text("1")
        (base / "src" / "__pycache__").mkdir()
        (base / "src" / "__pycache__" / "x.pyc").write_text("junk")
    (b / ".venv").mkdir()
    (b / ".venv" / "lib.py").write_text("env")
    assert differences(a, b) == []
    (a / "src" / "x.py").write_text("2")
    (a / "src" / "y.py").write_text("new")
    assert differences(a, b) == ["src/x.py", "src/y.py"]
    assert set(digests(b)) == {"src/x.py"}
    assert in_use("os error 32") and not in_use("exit 1")


def test_pacer_update_runs_the_source_installer_and_relays_it(origin, monkeypatch):
    _, checkout = origin
    home.update_state(lambda s: s.setdefault("install", {}).__setitem__("source", str(checkout)))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    args = argparse.Namespace(
        refresh=False, notify=None, demo=False, check=False, host="none", no_cli=True, force=False
    )
    assert update.update_main(args) == 0
    text = out.getvalue()
    assert "PACER update 3.0.0 -> 3.1.0" in text  # a StringIO has no encoding: ASCII glyphs
    assert "  ok  resolve        v3.1.0 on origin" in text
    assert "  ok  source         fast-forward" in text
    assert "  ok  Claude Code    pacer@mivim 3.1.0" in text
    assert "ready in" in text and "Start a new session to load it." in text
    assert update.source_version(checkout) == "3.1.0"
    assert home.read_state()["update"]["latest"] == "3.1.0"


def test_check_reports_without_changing_anything(origin, monkeypatch):
    _, checkout = origin
    home.update_state(lambda s: s.setdefault("install", {}).__setitem__("source", str(checkout)))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    args = argparse.Namespace(
        refresh=False, notify=None, demo=False, check=True, host="none", no_cli=True, force=False
    )
    assert update.update_main(args) == 1
    text = out.getvalue()
    assert (
        "  ok  installed      3.0.0 (checkout)" in text
        and "  !!  origin         v3.1.0 available" in text
    )
    assert text.rstrip().endswith("pacer update") and update.source_version(checkout) == "3.0.0"


def test_notify_switch_and_refresh_entry(origin, monkeypatch, capsys):
    _, checkout = origin
    home.update_state(lambda s: s.setdefault("install", {}).__setitem__("source", str(checkout)))
    off = argparse.Namespace(
        refresh=False, notify="off", demo=False, check=False, host="none", no_cli=True, force=False
    )
    assert update.update_main(off) == 0 and capsys.readouterr().out.strip() == "update notice off"
    assert home.read_state()["update"]["notify"] is False
    refresh = argparse.Namespace(
        refresh=True, notify=None, demo=False, check=False, host="none", no_cli=True, force=False
    )
    assert update.update_main(refresh) == 0 and home.read_state()["update"]["latest"] == "3.1.0"


def test_home_is_namespaced_and_overridable(monkeypatch, tmp_path):
    monkeypatch.delenv("PACER_HOME")
    assert home.home().parts[-2:] == ("mivim", "pacer")
    monkeypatch.setenv("PACER_HOME", str(tmp_path / "elsewhere"))
    assert home.home() == tmp_path / "elsewhere"
    assert home.read_state() == {}
    assert home.update_state(lambda s: s.__setitem__("k", 1)) is None
    assert home.read_state() == {"k": 1}
    (tmp_path / "elsewhere" / "state.json").write_text("not json")
    assert home.read_state() == {}


def test_spawned_refresh_detaches_and_writes_state(origin, monkeypatch):
    """The real detached process: it must not hold the parent's pipes or inherit a console."""
    _, checkout = origin
    monkeypatch.delenv("PACER_NO_UPDATE_CHECK")
    home.update_state(lambda s: s.setdefault("install", {}).__setitem__("source", str(checkout)))
    assert update.spawn_refresh() is True
    import time

    for _ in range(100):
        if home.read_state().get("update", {}).get("latest") == "3.1.0":
            break
        time.sleep(0.1)
    assert home.read_state()["update"]["latest"] == "3.1.0"
    assert os.environ.get("PACER_HOME")  # the child read the same isolated home
