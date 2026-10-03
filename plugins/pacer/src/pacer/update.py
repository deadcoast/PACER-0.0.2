"""Keeping PACER current.

Where the latest version is: the `v*` tags on the origin, read with git and the
credentials git already has, never an API. When to mention it: once for each new
version, in the terminal or at the start of an agent session, whichever comes
first, and never once silenced. How to get there: `pacer update`, which advances
the source, syncs each host whose copy differs, and keeps the command editable,
all under one Pace Line.

The check that feeds the notice runs in a detached process at most once a day
and never inside a hook's own time.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from pacer import __version__
from pacer.display import Journey, Step, StepError, report
from pacer.display import notice as card
from pacer.display.prompt import Option, choose
from pacer.home import home, read_state, update_state
from pacer.hosts import HOSTS, Command, Host, Note
from pacer.identity import PLUGIN, PLUGIN_ID, REPOSITORY

CHECK_EVERY = 24 * 3600
TAG = re.compile(r"refs/tags/v(\d+)\.(\d+)\.(\d+)$")
VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)")
# No prompt of any kind from a background check: it fails quietly instead.
GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never", "GIT_ASKPASS": "echo"}
EXPECT = {"resolve": 1.5, "source": 2.5, "claude": 6.0, "codex": 5.0, "command": 1.5}
LABELS = {"resolve": "resolve", "source": "source", "command": "command"}


# -- versions ------------------------------------------------------------------
def parse(text: str) -> tuple[int, int, int] | None:
    match = VERSION.match(text or "")
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def newer(candidate: str | None, than: str) -> bool:
    a, b = parse(candidate or ""), parse(than)
    return a is not None and (b is None or a > b)


def git(*args: str, cwd: Path | None = None, timeout: float = 30) -> tuple[int, str, str]:
    """Run git without ever prompting; (exit code, stdout, stderr)."""
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, **GIT_ENV},
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 1, "", "git could not be run"
    return done.returncode, done.stdout.strip(), done.stderr.strip()


def remote_versions(where: str | Path) -> list[str]:
    """Release versions on the origin, oldest first. `where` is a URL or a checkout."""
    target = ["origin"] if isinstance(where, Path) else [str(where)]
    cwd = where if isinstance(where, Path) else None
    _, out, _ = git("ls-remote", "--tags", "--refs", *target, "v*", cwd=cwd, timeout=20)
    found = {".".join(m.groups()) for m in (TAG.search(line) for line in out.splitlines()) if m}
    return sorted(found, key=lambda v: parse(v) or (0, 0, 0))


# -- the source ----------------------------------------------------------------
@dataclass
class Source:
    root: Path
    kind: str  # checkout: a repository someone works in; managed: PACER's own clone; kit: unpacked
    version: str


def managed_dir() -> Path:
    return home() / "source"


def is_source(root: Path) -> bool:
    return (root / "install.py").is_file() and (
        root / "plugins" / PLUGIN / "pyproject.toml"
    ).is_file()


def source_version(root: Path) -> str:
    try:
        text = (root / "plugins" / PLUGIN / "pyproject.toml").read_text(encoding="utf-8")
        return str(tomllib.loads(text)["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return ""


def describe(root: Path) -> Source:
    if not (root / ".git").exists():
        kind = "kit"
    elif root.resolve() == managed_dir().resolve():
        kind = "managed"
    else:
        kind = "checkout"
    return Source(root, kind, source_version(root))


def locate_source() -> Source | None:
    """The marketplace directory PACER was installed from, else the one this code runs in."""
    recorded = read_state().get("install", {}).get("source")
    candidates = [Path(recorded)] if recorded else []
    candidates.append(Path(__file__).resolve().parents[4])
    for candidate in candidates:
        if is_source(candidate):
            return describe(candidate)
    return None


def origin(source: Source | None) -> str:
    recorded = read_state().get("install", {}).get("origin")
    if recorded:
        return str(recorded)
    if source and source.kind != "kit":
        code, url, _ = git("remote", "get-url", "origin", cwd=source.root)
        if code == 0 and url:
            return url
    return REPOSITORY


def rev(root: Path) -> str:
    return git("rev-parse", "--short=7", "HEAD", cwd=root)[1] or "?"


def advance(source: Source, latest: str | None, note: Note) -> tuple[str, str, Path]:
    """Bring the source up to date. Returns (state, text, the root afterwards)."""
    root = source.root
    if source.kind == "kit":
        if not newer(latest, source.version):
            return "skip", f"kit {source.version}, no newer release", root
        target = managed_dir()
        note(f"cloning v{latest}")
        if (target / ".git").exists():
            git("fetch", "--tags", "--prune", "origin", cwd=target, timeout=120)
            code, _, err = git("checkout", "--quiet", "--detach", f"v{latest}", cwd=target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            code, _, err = git(
                "clone", "--quiet", "--branch", f"v{latest}", origin(source), str(target),
                timeout=300,
            )  # fmt: skip
        if code or not is_source(target):
            raise StepError(
                f"could not clone v{latest}: {err.splitlines()[-1] if err else 'unknown'}"
            )
        return "done", f"v{latest} cloned to {target}", target

    note("fetching origin")
    code, _, err = git("fetch", "--tags", "--prune", "origin", cwd=root, timeout=120)
    if code:
        return "skip", "origin unreachable, local source kept", root
    _, branch, _ = git("symbolic-ref", "-q", "--short", "HEAD", cwd=root)
    if branch:
        _, counts, _ = git("rev-list", "--left-right", "--count", "HEAD...@{u}", cwd=root)
        if not counts:
            return "skip", f"{branch} tracks no upstream", root
        ahead, behind = (int(n) for n in counts.split())
        if behind == 0:
            extra = f", {ahead} local commit(s) ahead" if ahead else ""
            return "skip", f"{branch} current{extra}", root
        if ahead:
            return "skip", f"{branch} diverged ({ahead} local, {behind} new); local work kept", root
        before = rev(root)
        note(f"fast-forwarding {behind} commit(s)")
        code, _, err = git("merge", "--ff-only", "--quiet", "@{u}", cwd=root)
        if code:
            return "skip", f"{behind} new commit(s) held back by local changes", root
        return "done", f"fast-forward {before}..{rev(root)}, {behind} commit(s)", root

    if not latest:
        return "skip", "no release on origin", root
    _, tag, _ = git("describe", "--tags", "--exact-match", cwd=root)
    if tag == f"v{latest}":
        return "skip", f"v{latest} current", root
    note(f"checking out v{latest}")
    code, _, err = git("checkout", "--quiet", "--detach", f"v{latest}", cwd=root)
    if code:
        raise StepError(f"could not check out v{latest}: {err.splitlines()[-1] if err else code}")
    return "done", f"v{latest} checked out", root


# -- the check and the notice ----------------------------------------------------
def silenced(env: dict[str, str] | None = None) -> bool:
    env = dict(os.environ) if env is None else env
    if env.get("PACER_NO_UPDATE_CHECK"):
        return True
    return read_state().get("update", {}).get("notify") is False


def set_notify(on: bool) -> None:
    update_state(lambda state: state.setdefault("update", {}).__setitem__("notify", on))


def refresh() -> str | None:
    """Ask the origin for the latest version and record it."""
    source = locate_source()
    where: str | Path = source.root if source and source.kind != "kit" else origin(source)
    latest = max(remote_versions(where), key=lambda v: parse(v) or (0, 0, 0), default=None)

    def change(state: dict) -> None:
        update = state.setdefault("update", {})
        update["checked_at"] = time.time()
        if latest:
            update["latest"] = latest

    update_state(change)
    return latest


def spawn_refresh() -> bool:
    """Start `pacer update --refresh` detached, so no caller waits for the network."""
    main = Path(__file__).with_name("__main__.py")
    command = [sys.executable, "-B", str(main), "update", "--refresh"]
    quiet = subprocess.DEVNULL
    try:
        if sys.platform == "win32":
            flags = 0x00000008 | 0x00000200 | 0x08000000  # detached, own group, no window
            subprocess.Popen(
                command,
                stdin=quiet,
                stdout=quiet,
                stderr=quiet,
                close_fds=True,
                creationflags=flags,
            )
        else:
            subprocess.Popen(
                command,
                stdin=quiet,
                stdout=quiet,
                stderr=quiet,
                close_fds=True,
                start_new_session=True,
            )
    except OSError:
        return False
    return True


def maybe_refresh(now: float | None = None) -> bool:
    """Start a background check when the last one is a day old. True when one was started."""
    if silenced():
        return False
    now = time.time() if now is None else now
    if now - read_state().get("update", {}).get("checked_at", 0) < CHECK_EVERY:
        return False
    # Claim the slot first: a burst of hooks must not start a burst of checks.
    update_state(lambda state: state.setdefault("update", {}).__setitem__("checked_at", now))
    return spawn_refresh()


def pending(state: dict, current: str = __version__) -> str | None:
    """A recorded version newer than `current` that has not been announced yet."""
    update = state.get("update", {})
    latest = update.get("latest")
    if (
        not isinstance(latest, str)
        or not newer(latest, current)
        or update.get("notified") == latest
    ):
        return None
    return latest


def take_notice(current: str = __version__) -> str | None:
    """The version to announce now, marked as announced so it is said once."""
    if silenced():
        return None
    found: dict[str, str | None] = {}

    def change(state: dict) -> None:
        found["latest"] = latest = pending(state, current)
        if latest:
            state.setdefault("update", {})["notified"] = latest

    update_state(change)
    return found.get("latest")


def session_notice(current: str = __version__) -> str:
    """For a hook at session start: plain text for the person, or nothing."""
    maybe_refresh()
    latest = take_notice(current)
    return card.text(current, latest) if latest else ""


def cli_notice(stream: TextIO, current: str = __version__) -> None:
    """After a command in a terminal: the styled notice, or nothing. Never raises."""
    try:
        if not (hasattr(stream, "isatty") and stream.isatty()):
            return
        maybe_refresh()
        latest = take_notice(current)
        if latest:
            stream.write(card.styled(current, latest, stream) + "\n")
            stream.flush()
    except Exception:  # noqa: BLE001 - a notice must never break the command it follows
        return


# -- the engine ----------------------------------------------------------------
def expected(step_id: str) -> float:
    """How long a stage took last time, else a default."""
    recorded = read_state().get("timings", {}).get(step_id)
    return (
        float(recorded)
        if isinstance(recorded, (int, float)) and recorded > 0
        else EXPECT.get(step_id, 3.0)
    )


def present_hosts(root: Path, wanted: str) -> list[Host]:
    names = list(HOSTS) if wanted == "all" else [] if wanted == "none" else [wanted]
    found = []
    for name in names:
        exe = shutil.which(name)
        if exe:
            found.append(HOSTS[name](exe, root))
    return found


def installed_text(host: Host) -> str:
    """One dim phrase beside a host's name in a prompt: what it runs now."""
    versions = sorted({c.version for c in host.copies() if c.plugin_id == PLUGIN_ID})
    return f"{', '.join(v or '?' for v in versions)} installed" if versions else "not installed"


def resolve_host(args: argparse.Namespace, root: Path) -> str | None:
    """Which hosts `pacer update` works on.

    `--claude`, `--codex`, `--all` and the scripting form `--host` decide when given.
    Otherwise, in a terminal with more than one host present, the person is asked;
    anywhere else every host is taken. None means the question was cancelled.
    """
    named = [name for name in HOSTS if getattr(args, name, False)]
    if getattr(args, "all", False) or len(named) == len(HOSTS):
        return "all"
    if named:
        return named[0]
    if args.host:
        return str(args.host)
    found = present_hosts(root, "all")
    if len(found) < 2:
        return "all"
    options = [Option(h.command, h.name, installed_text(h)) for h in found]
    options.append(Option("all", "both"))
    return choose("update", "where?", options, default=len(options) - 1)


def host_steps(hosts: list[Host], command: bool) -> list[Step]:
    steps = [Step(h.command, h.name, expected(h.command)) for h in hosts]
    if command:
        steps.append(Step("command", "command", expected("command")))
    return steps


def sync(
    root: Path,
    journey: Journey,
    hosts: list[Host],
    command: Command | None,
    *,
    force: bool = False,
) -> tuple[bool, list[str]]:
    """Each host and the command, one stage each. Returns (changed anything, advice)."""
    version = source_version(root)
    journey.plan(host_steps(hosts, command is not None))
    changed, advice = False, []
    for host in hosts:
        with journey.step(host.command, "comparing the installed copy") as stage:
            try:
                state, text = host.sync(version, stage.note, force=force)
            except RuntimeError as error:
                raise StepError(str(error)) from error
            (stage.done if state == "done" else stage.skip)(text)
            changed = changed or state == "done"
        advice += host.advice()
    if command:
        with journey.step("command", "checking the uv tool") as stage:
            record = read_state().get("install", {}).get("command", {})
            state, text, kept = command.sync(record, stage.note, force=force)
            (stage.done if state == "done" else stage.skip)(text)
            changed = changed or state == "done"
            update_state(lambda s: s.setdefault("install", {}).__setitem__("command", kept))
    source = describe(root)

    def record_install(state: dict) -> None:
        install = state.setdefault("install", {})
        install.update(
            source=str(root),
            origin=origin(source),
            version=version,
            kind=source.kind,
            at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        state.setdefault("timings", {}).update(journey.timings())

    update_state(record_install)
    return changed, advice


def finish(journey: Journey, changed: bool, advice: list[str], started: float) -> bool:
    took = time.monotonic() - started
    if not journey.ok:
        failed = next(step.label for step in journey.steps if step.state == "fail")
        return journey.close(
            f"stopped at {failed}", ["Nothing else changed. Run pacer update again."]
        )
    headline = f"ready in {took:.1f}s" if changed else "current"
    hints = ["Start a new session to load it."] if changed else []
    return journey.close(headline, [*hints, *advice])


# -- entry points ----------------------------------------------------------------
def install_main(root: Path, argv: list[str] | None = None) -> int:
    """`install.py`: run from a checkout or a kit, with or without a parent to report to."""
    parser = argparse.ArgumentParser(
        prog="install.py", description="Install PACER from this directory"
    )
    parser.add_argument("--host", choices=[*HOSTS, "all", "none"], default="all")
    parser.add_argument("--no-cli", action="store_true", help="leave the `pacer` command alone")
    parser.add_argument("--force", action="store_true", help="reinstall where a copy is current")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--status", action="store_true", help="report what each host runs")
    action.add_argument("--uninstall", action="store_true", help="remove PACER from every host")
    parser.add_argument("--events", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    uv = shutil.which("uv")
    if uv is None:
        print("uv is required: https://docs.astral.sh/uv/", file=sys.stderr)
        return 2
    hosts = present_hosts(root, args.host)
    if args.host not in {"all", "none"} and not hosts:
        print(f"{args.host} is not on PATH", file=sys.stderr)
        return 2
    command = None if args.no_cli else Command(uv, root / "plugins" / PLUGIN)
    version = source_version(root)
    if args.status:
        return 0 if status_report(root, version, hosts, command) else 1
    mode = "events" if args.events else None
    if args.uninstall:
        return uninstall(root, hosts, command, mode)
    started = time.monotonic()
    journey = Journey("install", host_steps(hosts, command is not None), detail=version, mode=mode)
    with journey:
        changed, advice = sync(root, journey, hosts, command, force=args.force)
        ok = finish(journey, changed, advice, started)
    return 0 if ok else 1


def status_report(root: Path, version: str, hosts: list[Host], command: Command | None) -> bool:
    rows: list[tuple[str, str, str]] = []
    for host in hosts:
        current, notes, _ = host.status(version)
        rows.append(("done" if current else "fail", host.name, "; ".join(notes)))
    if command:
        current, text = command.status(read_state().get("install", {}).get("command", {}))
        rows.append(("done" if current else "fail", "command", text))
    hints = [hint for host in hosts for hint in host.advice()]
    return report("status", rows, detail=f"{version}  {root}", hints=hints)


def uninstall(root: Path, hosts: list[Host], command: Command | None, mode: str | None) -> int:
    steps = [Step(h.command, h.name, 2.0) for h in hosts]
    if command:
        steps.append(Step("command", "command", 1.0))
    journey = Journey("uninstall", steps, mode=mode)
    with journey:
        for host in hosts:
            with journey.step(host.command) as stage:
                try:
                    notes = host.remove(keep_market=False)
                except RuntimeError as error:
                    raise StepError(str(error)) from error
                stage.done("; ".join(notes) or "nothing to remove")
        if command:
            with journey.step("command") as stage:
                stage.done(command.remove())
        update_state(lambda state: state.pop("install", None))
        ok = journey.close("removed" if journey.ok else "stopped")
    return 0 if ok else 1


def update_main(args: argparse.Namespace) -> int:
    """`pacer update` and its switches."""
    if args.refresh:
        refresh()
        return 0
    if args.notify:
        set_notify(args.notify == "on")
        print(f"update notice {args.notify}")
        return 0
    if args.demo:
        return demo()
    source = locate_source()
    if source is None:
        print(
            "pacer: the source directory is unknown; run install.py from a checkout or a kit",
            file=sys.stderr,
        )
        return 2
    if args.check:
        return check(source, args)
    # The one question the command asks, and only of a person: where.
    wanted = resolve_host(args, source.root)
    if wanted is None:
        return 1
    args.host = wanted
    return run_update(source, args)


def check(source: Source, args: argparse.Namespace) -> int:
    latest = refresh()
    rows = [("done", "installed", f"{source.version} ({source.kind}) {source.root}")]
    if latest is None:
        rows.append(("fail", "origin", "unreachable"))
    elif newer(latest, source.version):
        rows.append(("fail", "origin", f"v{latest} available"))
    else:
        rows.append(("done", "origin", f"v{latest}, current"))
    uv = shutil.which("uv")
    hosts = present_hosts(source.root, args.host or "all")
    command = None if args.no_cli or uv is None else Command(uv, source.root / "plugins" / PLUGIN)
    for host in hosts:
        current, notes, _ = host.status(source.version)
        rows.append(("done" if current else "fail", host.name, "; ".join(notes)))
    if command:
        current, text = command.status(read_state().get("install", {}).get("command", {}))
        rows.append(("done" if current else "fail", "command", text))
    hints = ["pacer update"] if any(state == "fail" for state, _, _ in rows) else []
    return 0 if report("check", rows, hints=hints) else 1


def run_update(source: Source, args: argparse.Namespace) -> int:
    started = time.monotonic()
    hosts = present_hosts(source.root, args.host)
    steps = [
        Step("resolve", "resolve", expected("resolve")),
        Step("source", "source", expected("source")),
        *host_steps(hosts, not args.no_cli),
    ]
    journey = Journey("update", steps, detail=source.version)
    root, latest = source.root, None
    with journey:
        with journey.step("resolve", "reading origin") as stage:
            latest = refresh()
            if latest is None:
                stage.skip("origin unreachable")
            elif newer(latest, source.version):
                journey.retitle(f"{source.version} {journey.arrow} {latest}")
                stage.done(f"v{latest} on origin")
            else:
                stage.done(f"v{latest} on origin, current")
        with journey.step("source") as stage:
            state, text, root = advance(source, latest, stage.note)
            (stage.done if state == "done" else stage.skip)(text)
        version = source_version(root)
        if version != source.version:
            journey.retitle(f"{source.version} {journey.arrow} {version}")
        changed, advice, failed = relay_install(root, journey, args)
        if failed:
            journey.plan([Step("install", "install", 1.0)])
            journey.begin("install")
            journey.end("install", "fail", failed)
        ok = finish(journey, changed, advice, started)
    update_state(lambda state: state.setdefault("timings", {}).update(journey.timings()))
    return 0 if ok else 1


def relay_install(
    root: Path, journey: Journey, args: argparse.Namespace
) -> tuple[bool, list[str], str]:
    flags = ["--host", args.host]
    if args.no_cli:
        flags.append("--no-cli")
    if args.force:
        flags.append("--force")
    return run_installer(root, journey, flags)


def run_installer(root: Path, journey: Journey, flags: list[str]) -> tuple[bool, list[str], str]:
    """Run the source's own installer, which may be newer than this code, and render its events.

    Returns (changed anything, advice, failure text); the failure text is empty when the
    installer reported through its own journey, failed stages included.
    """
    child = subprocess.Popen(
        [sys.executable, "-B", str(root / "install.py"), "--events", *flags],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PACER_DISPLAY": "events"},
    )
    closing: dict = {}
    noise: list[str] = []
    assert child.stdout is not None
    for line in child.stdout:
        data = journey.relay(line)
        if data is None and line.strip():
            noise.append(line.rstrip())
        elif data and data.get("event") == "close":
            closing = data
    code = child.wait()
    if code and not closing:
        tail = "; ".join(noise[-3:]) or f"exit {code}"
        return False, [], f"the installer stopped: {tail}"
    changed = closing.get("headline", "").startswith("ready")
    advice = [hint for hint in closing.get("hints", []) if not hint.startswith("Start a new")]
    return changed, advice, ""


def demo() -> int:
    """Play the display without changing anything."""
    steps = [Step(k, LABELS.get(k, k), v) for k, v in EXPECT.items()]
    for step in steps:
        if step.id in HOSTS:
            step.label = HOSTS[step.id].name
    journey = Journey("update", steps, detail=f"{__version__} ▸ {__version__}")
    done, skip = "done", "skip"
    script: dict[str, list[tuple[float, str, tuple[str, str] | None]]] = {
        "resolve": [
            (0.6, "reading origin", None),
            (0.0, "", (done, f"v{__version__} on origin")),
        ],
        "source": [
            (0.7, "fetching origin", None),
            (0.5, "fast-forwarding 7 commit(s)", None),
            (0.0, "", (done, "fast-forward a1b2c3d..d4e5f6a, 7 commit(s)")),
        ],
        "claude": [
            (0.8, "comparing the installed copy", None),
            (1.0, f"removed {PLUGIN_ID}", None),
            (1.4, f"installed {PLUGIN_ID}", None),
            (0.0, "", (done, f"{PLUGIN_ID} {__version__}, 12 file(s) refreshed")),
        ],
        "codex": [
            (0.9, "comparing the installed copy", None),
            (0.0, "", (skip, f"{PLUGIN_ID} {__version__} current")),
        ],
        "command": [
            (0.5, "checking the uv tool", None),
            (0.0, "", (skip, "pacer command current")),
        ],
    }
    started = time.monotonic()
    with journey:
        for step in steps:
            with journey.step(step.id) as stage:
                for pause, note, outcome in script[step.id]:
                    if note:
                        stage.note(note)
                    time.sleep(pause)
                    if outcome:
                        (stage.done if outcome[0] == "done" else stage.skip)(outcome[1])
        finish(journey, True, [], started)
    return 0
