"""`pacer doctor`: what is wrong with this installation, and the repairs it owns.

    pacer doctor               the vitals: machine, hosts, project; exit 1 on a failure
    pacer doctor --fix         apply every repair the doctor owns, then read the vitals again
    pacer doctor ~/work/app    the project checks for another directory

Every check is one row with a verdict. A row the doctor can repair names no
command: `--fix` does it. A row it cannot repair names the one command that
does. Nothing here changes anything without `--fix`.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pacer.display import Journey, Step, StepError, report
from pacer.home import home, read_state, update_state
from pacer.hosts import Command, Host, Note, call
from pacer.identity import PLUGIN
from pacer.layout import FORMAT, Layout, find_root, register_name
from pacer.probe import freshness
from pacer.service import Service
from pacer.update import (
    Source,
    expected,
    locate_source,
    newer,
    present_hosts,
    refresh,
    silenced,
    source_version,
)

GROUPS = ("machine", "hosts", "project")
Fixer = Callable[[Note], str]


@dataclass
class Finding:
    group: str
    name: str
    state: str  # done | warn | fail | skip
    text: str
    remedy: str = ""  # the command for the person, when the doctor cannot repair it
    fix: Fixer | None = None  # the repair, when it can
    expect: float = 2.0

    @property
    def id(self) -> str:
        return f"{self.group}.{self.name}".replace(" ", "-")


# -- the machine ------------------------------------------------------------------
def machine(source: Source | None) -> list[Finding]:
    found: list[Finding] = []
    uv = shutil.which("uv")
    if uv:
        found.append(Finding("machine", "uv", "done", f"{_first(call(uv, '--version')[1])}  {uv}"))
        found.append(python(uv))
    else:
        found.append(
            Finding("machine", "uv", "fail", "not on PATH", remedy="install uv: docs.astral.sh/uv")
        )
    git = shutil.which("git")
    found.append(
        Finding("machine", "git", "done", _first(call(git, "--version")[1]))
        if git
        else Finding("machine", "git", "fail", "not on PATH", remedy="install git")
    )
    if source is None:
        found.append(
            Finding(
                "machine",
                "source",
                "fail",
                "unknown",
                remedy="run install.py from a checkout or a kit",
            )
        )
    else:
        found.append(
            Finding("machine", "source", "done", f"{source.version} ({source.kind})  {source.root}")
        )
        found.append(origin(source))
    found.append(home_dir())
    return found


def python(uv: str) -> Finding:
    """An interpreter uv can start hooks with, from a bare environment."""
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    try:
        done = subprocess.run(
            [uv, "python", "find", "--no-project", ">=3.11"],
            cwd=home() if home().is_dir() else None,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        done = None
    if done is None or done.returncode or not done.stdout.strip():
        return Finding(
            "machine",
            "python",
            "fail",
            "no interpreter 3.11 or newer",
            remedy="uv python install 3.13",
        )
    path = done.stdout.strip().splitlines()[-1]
    version = _first(call(path, "--version")[1]).removeprefix("Python ")
    return Finding("machine", "python", "done", f"{version}  {path}")


def origin(source: Source) -> Finding:
    latest = refresh()
    if latest is None:
        return Finding("machine", "origin", "warn", "unreachable; the last known version stands")
    if newer(latest, source.version):
        return Finding("machine", "origin", "warn", f"v{latest} available", remedy="pacer update")
    return Finding("machine", "origin", "done", f"v{latest}, current")


def home_dir() -> Finding:
    where = home()
    if update_state(lambda _: True) is None:
        return Finding("machine", "home", "fail", f"{where} is not writable")
    extra = "  (notices off)" if silenced() else ""
    return Finding("machine", "home", "done", f"{where}{extra}")


# -- the hosts --------------------------------------------------------------------
def hosts(found: list[Host], source: Source | None, root: Path | None) -> list[Finding]:
    rows: list[Finding] = []
    if not found:
        rows.append(Finding("hosts", "hosts", "warn", "neither claude nor codex is on PATH"))
    version = source.version if source else ""
    for host in found:
        rows += one_host(host, version, root)
    return rows


def one_host(host: Host, version: str, root: Path | None) -> list[Finding]:
    rows: list[Finding] = []
    current, notes, _ = host.status(version)
    text = "; ".join(notes)
    if current:
        rows.append(Finding("hosts", host.name, "done", text))
    elif not version:
        rows.append(Finding("hosts", host.name, "fail", text or "cannot compare: source unknown"))
    else:

        def resync(note: Note, host: Host = host) -> str:
            return host.sync(version, note)[1]

        rows.append(
            Finding("hosts", host.name, "fail", text, fix=resync, expect=expected(host.command))
        )
    stale = host.stale_copies()
    if stale:
        names = ", ".join(d.name for d in stale)

        def drop(_: Note, host: Host = host) -> str:
            removed = host.drop_stale()
            return f"removed {', '.join(removed)}" if removed else "nothing could be removed"

        rows.append(
            Finding(
                "hosts",
                f"{host.name} cache",
                "warn",
                f"stale cop{'y' if len(stale) == 1 else 'ies'}: {names}",
                fix=drop,
            )
        )
    else:
        rows.append(
            Finding("hosts", f"{host.name} cache", "done", "one copy per installed version")
        )
    enabled = host.hooks_enabled()
    if enabled is False:
        rows.append(
            Finding(
                "hosts",
                f"{host.name} hooks",
                "warn",
                "disabled: no frames arrive",
                remedy=f"{host.command} features enable hooks, then trust them once with /hooks",
            )
        )
    elif enabled:
        rows.append(Finding("hosts", f"{host.name} hooks", "done", "enabled"))
    if root is not None and Layout(root).governed() and host.scoped:
        if host.enrolled(root):
            rows.append(
                Finding("hosts", f"{host.name} project", "done", f"enabled for {root.name}")
            )
        else:
            rows.append(
                Finding(
                    "hosts",
                    f"{host.name} project",
                    "skip",
                    "user scope only",
                    remedy=f"pacer init {root} --{host.command} enables it for this project",
                )
            )
    return rows


def command(tool: Command | None) -> list[Finding]:
    if tool is None:
        return [Finding("hosts", "command", "skip", "needs uv and the source")]
    record = read_state().get("install", {}).get("command", {})
    current, text = tool.status(record)
    launcher = shutil.which(PLUGIN)
    rows: list[Finding] = []
    if current:
        rows.append(Finding("hosts", "command", "done", text))
    else:

        def reinstall(note: Note) -> str:
            _, text, kept = tool.sync(record, note)
            update_state(lambda s: s.setdefault("install", {}).__setitem__("command", kept))
            return text

        rows.append(
            Finding("hosts", "command", "fail", text, fix=reinstall, expect=expected("command"))
        )
    if launcher is None:
        rows.append(
            Finding(
                "hosts",
                "command path",
                "warn",
                "pacer is not on PATH",
                remedy="add uv's tool directory to PATH: uv tool update-shell",
            )
        )
    else:
        rows.append(Finding("hosts", "command path", "done", launcher))
    return rows


# -- the project ------------------------------------------------------------------
def project(root: Path | None) -> list[Finding]:
    if root is None or not Layout(root).governed():
        where = root or Path.cwd()
        return [
            Finding(
                "project",
                "registers",
                "skip",
                f"{where} is not governed",
                remedy=f"pacer init {where}",
            )
        ]
    rows: list[Finding] = []
    layout = Layout(root)
    service = Service(root)
    if layout.journal.exists():

        def recover(_: Note) -> str:
            try:
                result = service.recover()
            except ValueError as error:
                raise RuntimeError(str(error)) from error
            return (
                "journal rolled forward"
                if result.get("recovered")
                else "journal could not be applied"
            )

        rows.append(
            Finding("project", "journal", "warn", "an interrupted write is pending", fix=recover)
        )
    try:
        verdict = service.validate()
    except (OSError, ValueError) as error:
        rows.append(Finding("project", "registers", "fail", str(error)))
        return rows
    if verdict["valid"]:
        count = len(verdict.get("warnings", []))
        rows.append(
            Finding(
                "project", "registers", "done", f"valid, {count} warning(s)" if count else "valid"
            )
        )
    else:
        rows.append(
            Finding("project", "registers", "fail", verdict["errors"][0], remedy="pacer validate")
        )
    rows.append(fmt(layout))
    rows.append(tracking(root, layout))
    rows.append(evidence(service))
    return rows


def fmt(layout: Layout) -> Finding:
    try:
        data = tomllib.loads(layout.config.read_text(encoding="utf-8"))
        found = str(data.get("format", ""))
    except (OSError, tomllib.TOMLDecodeError):
        return Finding("project", "format", "fail", f"{layout.config.name} cannot be read")
    if found.split(".")[0] != FORMAT.split(".")[0]:
        return Finding(
            "project",
            "format",
            "warn",
            f"format {found or '?'}, this PACER writes {FORMAT}",
            remedy="pacer migrate",
        )
    return Finding("project", "format", "done", f"format {found}")


def tracking(root: Path, layout: Layout) -> Finding:
    if not (root / ".git").exists():
        return Finding("project", "tracking", "skip", "not a git repository")
    try:
        done = subprocess.run(
            ["git", "check-ignore", "-q", f"{layout.state.name}/{register_name('todo')}"],
            cwd=root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return Finding("project", "tracking", "skip", "git could not be asked")
    if done.returncode == 0:
        return Finding(
            "project",
            "tracking",
            "warn",
            f"{layout.state.name}/ is git-ignored; registers are not tracked",
            remedy=f"remove {layout.state.name} from .gitignore",
        )
    return Finding("project", "tracking", "done", "registers are tracked")


def evidence(service: Service) -> Finding:
    with service.store.locked():
        tables = service.store.load().tables
    proven = [r for r in tables["organism"] if r["Status"] == "VALIDATED_COMPLETE"]
    if not proven:
        return Finding("project", "evidence", "skip", "no proven requirements")
    off = {r["ID"]: freshness(r, tables, service.root) for r in proven}
    behind = sorted(k for k, v in off.items() if v != "CURRENT")
    if behind:
        return Finding(
            "project",
            "evidence",
            "warn",
            f"{len(behind)} of {len(proven)} proven not current: {', '.join(behind[:4])}"
            + ("…" if len(behind) > 4 else ""),
            remedy=f"pacer probe {behind[0]}",
        )
    return Finding("project", "evidence", "done", f"{len(proven)} proven, all current")


# -- the command ------------------------------------------------------------------
def examine(
    root: Path | None, source: Source | None, found: list[Host], tool: Command | None
) -> list[Finding]:
    return [*machine(source), *hosts(found, source, root), *command(tool), *project(root)]


def show(findings: list[Finding], *, fixing: bool, detail: str) -> bool:
    rows: list[tuple[str, str, str]] = []
    for group in GROUPS:
        rows.append(("head", group, ""))
        rows += [(f.state, f.name, f.text) for f in findings if f.group == group]
    hints: list[str] = []
    for finding in findings:
        if (
            finding.state in ("warn", "fail", "skip")
            and finding.remedy
            and finding.remedy not in hints
        ):
            hints.append(finding.remedy)
    repairs = [f for f in findings if f.fix is not None]
    if repairs and not fixing:
        hints.insert(0, f"pacer doctor --fix repairs {len(repairs)} of these")
    return report("doctor", rows, detail=detail, hints=hints)


def repair(findings: list[Finding]) -> bool:
    repairs = [f for f in findings if f.fix is not None]
    journey = Journey("doctor", [Step(f.id, f.name, f.expect) for f in repairs], detail="repairs")
    with journey:
        for finding in repairs:
            with journey.step(finding.id) as stage:
                try:
                    assert finding.fix is not None
                    stage.done(finding.fix(stage.note))
                except RuntimeError as error:
                    raise StepError(str(error)) from error
        ok = journey.close("repaired" if journey.ok else "a repair failed")
    return ok


def doctor_main(args: argparse.Namespace) -> int:
    started = time.monotonic()
    root = Path(args.path).expanduser().resolve() if args.path else find_root(Path.cwd())
    source = locate_source()
    uv = shutil.which("uv")
    anchor = source.root if source else Path.cwd()
    found = present_hosts(anchor, "all")
    tool = Command(uv, source.root / "plugins" / PLUGIN) if uv and source else None
    findings = examine(root, source, found, tool)
    version = source_version(source.root) if source else "?"
    show(findings, fixing=args.fix, detail=version)
    if args.fix and any(f.fix is not None for f in findings):
        repair(findings)
        findings = examine(root, source, found, tool)
        show(
            findings,
            fixing=True,
            detail=f"{version}  after repairs  {time.monotonic() - started:.0f}s",
        )
    return 0 if not any(f.state == "fail" for f in findings) else 1


def _first(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else "unknown"
