"""`pacer init`: a project under PACER, enrolled with the agent that will work in it.

    pacer init                              .pacer/ here, as before; JSON for an agent
    pacer init ~/work/app --claude          .pacer/ there, and Claude Code enabled for it
    pacer init --codex                      .pacer/ here, Codex checked and ready
    pacer init                              in a terminal: asks for the path, then the host

Enrolling a host means it runs PACER for this project from the installed
source: Claude Code gets the plugin enabled at project scope, which the
repository then carries in `.claude/settings.json`; Codex runs every plugin
at user scope, so it is installed if missing and its hooks switch is checked.
A project that is already governed keeps its registers and is enrolled anyway.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

from pacer import migrate
from pacer.display import Journey, Step, StepError
from pacer.display.keys import available
from pacer.display.prompt import Option, Scan, ask_path, choose
from pacer.display.term import detect
from pacer.hosts import HOSTS, Host
from pacer.identity import PLUGIN_ID
from pacer.layout import CONFIG_NAME, STATE_DIR
from pacer.schema import REGISTERS
from pacer.service import Service
from pacer.update import Source, expected, locate_source, source_version

MARKERS = ("CLAUDE.md", "AGENTS.md", ".claude", ".codex")


def live_terminal(env: dict[str, str] | None = None) -> bool:
    """Whether the human layer applies: prompts and the live display."""
    env = dict(os.environ) if env is None else env
    return available() and detect(sys.stdout, env).live and env.get("PACER_DISPLAY") != "plain"


def scan_project(path: Path | None, default: Path) -> Scan:
    """What a directory would mean to `pacer init`, for the field's live line."""
    target = default if path is None else path
    if not target.exists():
        return Scan("bad", ["does not exist"])
    if not target.is_dir():
        return Scan("bad", ["not a directory"])
    try:
        entries = list(os.scandir(target))
    except OSError:
        return Scan("bad", ["cannot be read"])
    names = {entry.name for entry in entries}
    state, notes = "good", []
    if ".git" in names:
        notes.append("git repository")
    if (target / STATE_DIR / CONFIG_NAME).is_file():
        state = "warn"
        notes.append("already governed, registers are kept")
    elif migrate.detect(target):
        state = "warn"
        notes.append("older PACER format: pacer migrate")
    else:
        notes.append("not yet governed")
    notes += [marker for marker in MARKERS if marker in names]
    notes.append(f"{len(entries)} entries")
    return Scan(state, notes)


def flagged(args: argparse.Namespace) -> list[str]:
    """Host names named on the command line, in HOSTS order."""
    if getattr(args, "all", False):
        return list(HOSTS)
    return [name for name in HOSTS if getattr(args, name, False)]


def present(root: Path, names: list[str]) -> list[Host]:
    return [HOSTS[n](exe, root) for n in names if (exe := shutil.which(n))]


def ask_hosts(root: Path, env: dict[str, str] | None = None) -> list[str] | None:
    """Which hosts to enrol, asked in the terminal; None when cancelled."""
    found = present(root, list(HOSTS))
    options = [Option(h.command, h.name, _installed(h)) for h in found]
    if len(found) > 1:
        options.append(Option("all", "both"))
    options.append(Option("none", "registers only", "no host; an agent will find .pacer/"))
    default = len(options) - 2 if found else 0
    chosen = choose("init", "which agent?", options, default=default, env=env)
    if chosen is None:
        return None
    return list(HOSTS) if chosen == "all" else [] if chosen == "none" else [chosen]


def _installed(host: Host) -> str:
    versions = sorted({c.version for c in host.copies() if c.plugin_id == PLUGIN_ID})
    return f"{', '.join(versions)} installed" if versions else "not installed"


def init_main(args: argparse.Namespace) -> int:
    live = live_terminal()
    wanted = flagged(args)
    path: Path | None = args.path or args.root
    if path is None:
        path = (
            ask_path("init", "where?", default=Path.cwd(), scan=_scanner()) if live else Path.cwd()
        )
        if path is None:
            return 1
    path = path.expanduser().resolve()
    if not path.is_dir():
        print(f"pacer: {path} is not a directory", file=sys.stderr)
        return 2
    if not wanted and live:
        asked = ask_hosts(path)
        if asked is None:
            return 1
        wanted = asked
    if not wanted and not live:
        # The agent layer: unchanged, one JSON document.
        result = Service(path).init(args.name, args.tier)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result.get("valid", True) else 1

    source = locate_source() if wanted else None
    if wanted and source is None:
        print(
            "pacer: PACER's source is unknown; run install.py from a checkout first",
            file=sys.stderr,
        )
        return 2
    hosts = present(source.root, wanted) if source else []
    missing = [n for n in wanted if n not in {h.command for h in hosts}]
    for name in missing:
        print(f"pacer: {name} is not on PATH", file=sys.stderr)
    if missing:
        return 2
    return run_init(path, args.name, args.tier, hosts, source)


def _scanner():
    cwd = Path.cwd()
    return lambda path: scan_project(path, cwd)


def run_init(path: Path, name: str, tier: str, hosts: list[Host], source: Source | None) -> int:
    started = time.monotonic()
    steps = [Step("registers", "registers", 1.0)]
    steps += [Step(h.command, h.name, expected(h.command)) for h in hosts]
    journey = Journey("init", steps, detail=path.name)
    advice: list[str] = []
    with journey:
        with journey.step("registers") as stage:
            try:
                Service(path).init(name, tier)
            except ValueError as error:
                if "already exists" not in str(error):
                    raise StepError(str(error)) from error
                stage.skip("already governed, registers kept")
            else:
                stage.done(f"{len(REGISTERS)} registers, tier {tier}")
        version = source_version(source.root) if source else ""
        for host in hosts:
            with journey.step(host.command, "checking the installed copy") as stage:
                try:
                    state, text = host.sync(version, stage.note)
                    stage.note(text)
                    enrolled = host.enroll(path)
                except RuntimeError as error:
                    raise StepError(str(error)) from error
                stage.done(enrolled if state == "skip" else f"{text}; {enrolled}")
            advice += host.advice()
        took = time.monotonic() - started
        if journey.ok:
            hints = [f"Open a session in {path}: the frame arrives at session start.", *advice]
            ok = journey.close(f"{path.name} governed in {took:.1f}s", hints)
        else:
            failed = next(s.label for s in journey.steps if s.state == "fail")
            ok = journey.close(f"stopped at {failed}", ["Run pacer doctor for the details."])
    return 0 if ok else 1
