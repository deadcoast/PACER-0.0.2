"""The `pacer` command.

Two layers share one command. Agents and scripts use the plain layer: every
subcommand takes its arguments on the line, prints JSON or cards, and never
asks anything. People use three of them above all, and those carry a human
layer that only exists in a terminal:

    pacer update          asks where when no host is named; the Pace Line while it runs
    pacer init            asks for the path and the agent when they are missing
    pacer doctor          the vitals of the machine, the hosts and the project

`hook` is the harness entry point; `serve` is the MCP entry point.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pacer import __version__
from pacer.identity import AGENTS
from pacer.layout import find_root
from pacer.migrate import SOURCES

FRAMES = ("session", "edit", "prompt", "stop")
HOOK_EVENTS = ("session-start", "prompt", "pre-edit", "post-edit", "stop")


def host_flags(parser: argparse.ArgumentParser, verb: str) -> None:
    """`--claude`, `--codex` and `--all`: which agent a command concerns."""
    group = parser.add_argument_group("hosts")
    for name, shown in AGENTS.items():
        group.add_argument(f"--{name}", action="store_true", help=f"{verb} {shown}")
    group.add_argument("--all", action="store_true", help=f"{verb} every host on PATH")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pacer",
        description="PACER: delivered project context",
        epilog="In a terminal, init and update ask for what is missing; doctor finds and fixes.",
    )
    parser.add_argument("--version", action="version", version=f"pacer {__version__}")
    parser.add_argument("--root", type=Path, help="project root (default: nearest .pacer/ upward)")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser(
        "init",
        help="create .pacer/ and enrol the project with an agent",
        description="Create .pacer/ with empty registers. With --claude or --codex the project "
        "is also enrolled with that agent. In a terminal, a missing path or agent is asked for.",
    )
    init.add_argument("path", nargs="?", type=Path, help="the project (default: here)")
    init.add_argument("--name", default="", help="project name (default: directory name)")
    init.add_argument("--tier", default="prototype")
    host_flags(init, "enrol the project with")

    doctor = sub.add_parser(
        "doctor",
        help="check the installation and the project; --fix repairs what it can",
        description="The vitals of the machine, each host and the project, one row each. "
        "--fix applies every repair the doctor owns and names the command for the rest.",
    )
    doctor.add_argument("path", nargs="?", type=Path, help="the project (default: here)")
    doctor.add_argument("--fix", action="store_true", help="apply the repairs")

    frame = sub.add_parser("frame", help="compile a card frame")
    frame.add_argument("kind", choices=FRAMES)
    frame.add_argument("--focus", default="", help="path for edit, text for prompt")

    q = sub.add_parser("q", help="cards for an ID, path, #tag, register or register:STATUS")
    q.add_argument("query")
    q.add_argument("--limit", type=int, default=40)

    write = sub.add_parser("write", help="apply a JSON array of operations")
    write.add_argument("--file", required=True, type=Path, help="operations file, or - for stdin")
    write.add_argument("--actor", required=True)
    write.add_argument("--preview", action="store_true")

    probe = sub.add_parser("probe", help="run a requirement's Probe and record its evidence")
    probe.add_argument("id")
    probe.add_argument("--actor", default="cli")

    sync = sub.add_parser("sync", help="retire asset rows whose file is gone")
    sync.add_argument("--apply", action="store_true")
    sync.add_argument("--actor", default="cli")

    upgrade = sub.add_parser("migrate", help="bring an older PACER project to this layout")
    upgrade.add_argument("--from", dest="source", choices=SOURCES, help="default: detect")
    upgrade.add_argument("--apply", action="store_true")
    upgrade.add_argument("--actor", default="cli")

    log = sub.add_parser("log", help="ledger events, newest last")
    log.add_argument("id", nargs="?", default="")
    log.add_argument("--limit", type=int, default=20)

    for name, text in (
        ("validate", "check every register and reference"),
        ("tree", "the work tree as indented cards"),
        ("recover", "finish an interrupted write"),
    ):
        sub.add_parser(name, help=text)

    serve = sub.add_parser("serve", help="run the MCP stdio server")
    serve.add_argument("--bind", type=Path, help="serve only this project root")

    hook = sub.add_parser("hook", help="harness hook; reads the event JSON on stdin")
    hook.add_argument("event", choices=HOOK_EVENTS)

    update = sub.add_parser(
        "update",
        help="bring PACER to the latest version in a host, or in every host",
        description="Advance the source to the latest release, sync each chosen host whose "
        "installed copy differs, and keep the pacer command current. Without a host flag, "
        "a terminal asks where; a script gets every host.",
    )
    update.add_argument("--check", action="store_true", help="report versions; change nothing")
    update.add_argument(
        "--force", action="store_true", help="reinstall even where a copy is current"
    )
    host_flags(update, "update")
    update.add_argument("--host", choices=[*AGENTS, "all", "none"], help=argparse.SUPPRESS)
    update.add_argument("--no-cli", action="store_true", help="leave the `pacer` command alone")
    update.add_argument(
        "--notify", choices=["on", "off"], help="announce a new version once (default on)"
    )
    update.add_argument("--refresh", action="store_true", help=argparse.SUPPRESS)
    update.add_argument("--demo", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "hook":
            return _hook(args.event)
        if args.command == "serve":
            from pacer.server import build_server

            build_server(args.bind).run(transport="stdio")
            return 0
        if args.command == "update":
            from pacer.update import update_main

            return update_main(args)
        if args.command == "init":
            from pacer.initiate import init_main

            code = init_main(args)
        elif args.command == "doctor":
            from pacer.doctor import doctor_main

            code = doctor_main(args)
        else:
            code = _command(args)
    except (ValueError, OSError) as exc:
        print(f"pacer: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return 130
    # A person ran a command in a terminal: the one place a newer version is mentioned.
    from pacer.update import cli_notice

    cli_notice(sys.stderr)
    return code


def _hook(event: str) -> int:
    from pacer.hook import run

    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    try:
        code, out = run(event, payload if isinstance(payload, dict) else {})
    except Exception as exc:  # noqa: BLE001 - a hook must never break the agent's turn
        print(f"pacer hook {event}: {exc}", file=sys.stderr)
        return 0
    if out:
        sys.stdout.write(out + "\n")
    return code


def _command(args) -> int:
    from pacer.service import Service

    root = args.root or (Path.cwd() if args.command == "migrate" else find_root(Path.cwd()))
    if root is None:
        raise ValueError("no .pacer/ here or above; run `pacer init` or pass --root")
    service = Service(root)
    if args.command == "frame":
        print(service.frame(args.kind, args.focus))
    elif args.command == "q":
        print(service.q(args.query, args.limit))
    elif args.command == "tree":
        print(service.tree())
    elif args.command == "log":
        for entry in service.log(args.id or None, args.limit):
            print(json.dumps(entry, ensure_ascii=False))
    else:
        if args.command == "write":
            text = sys.stdin.read() if str(args.file) == "-" else args.file.read_text("utf-8")
            result = service.write(json.loads(text), args.actor, preview=args.preview)
        elif args.command == "probe":
            result = service.probe(args.id, args.actor)
        elif args.command == "sync":
            result = service.sync(args.actor, preview=not args.apply)
        elif args.command == "migrate":
            result = service.migrate(args.source, actor=args.actor, preview=not args.apply)
        else:
            result = getattr(service, args.command)()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        valid = result.get("valid", result.get("validation", {}).get("valid", True))
        return 0 if valid else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
