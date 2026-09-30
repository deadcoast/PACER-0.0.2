"""PACER CLI; `hook` is the harness entry point; `serve` is the MCP entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pacer_mcp.service import Service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pacer", description="PACER 3: delivered context")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    frame = sub.add_parser("frame", help="Compile a bounded card frame")
    frame.add_argument("kind", choices=["session", "edit", "prompt", "stop"])
    frame.add_argument("--focus", default="")
    q = sub.add_parser("q", help="Cards for an ID, path, #tag, register or register:STATUS")
    q.add_argument("query")
    q.add_argument("--limit", type=int, default=40)
    write = sub.add_parser("write", help="Apply a JSON array of lexicon operations")
    write.add_argument("--file", required=True, type=Path)
    write.add_argument("--actor", required=True)
    write.add_argument("--preview", action="store_true")
    probe = sub.add_parser("probe", help="Run an OGM Probe and record its evidence")
    probe.add_argument("id")
    probe.add_argument("--actor", default="cli")
    for name in ("validate", "initialize", "tree", "recover"):
        sub.add_parser(name)
    migrate = sub.add_parser("migrate", help="Migrate 0.5 registers or a v2 plan")
    migrate.add_argument("--from", dest="source", required=True, choices=["0.5", "v2"])
    migrate.add_argument("--apply", action="store_true")
    migrate.add_argument("--actor", default="migrate")
    log = sub.add_parser("log", help="Ledger events, newest last")
    log.add_argument("id", nargs="?", default="")
    log.add_argument("--limit", type=int, default=20)
    serve = sub.add_parser("serve", help="Run the MCP stdio server")
    serve.add_argument("--root", dest="serve_root", type=Path)
    hook = sub.add_parser("hook", help="Harness hook entry; reads the event JSON on stdin")
    hook.add_argument("event", choices=["session-start", "prompt", "pre-edit", "post-edit", "stop"])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "serve":
            from pacer_mcp.server import build_server

            build_server(args.serve_root).run(transport="stdio")
            return 0
        if args.command == "hook":
            from pacer_mcp.hook import run

            try:
                payload = json.loads(sys.stdin.read() or "{}")
            except json.JSONDecodeError:
                payload = {}
            code, out = run(args.event, payload)
            if out:
                print(out)
            return code
        service = Service(args.root)
        if args.command == "frame":
            print(service.frame(args.kind, args.focus))
        elif args.command == "q":
            print(service.q(args.query, args.limit))
        elif args.command == "write":
            ops = json.loads(args.file.read_text(encoding="utf-8"))
            print(json.dumps(service.write(ops, args.actor, preview=args.preview), indent=2))
        elif args.command == "probe":
            print(json.dumps(service.probe(args.id, args.actor), indent=2))
        elif args.command == "migrate":
            result = service.migrate(args.source, actor=args.actor, preview=not args.apply)
            print(json.dumps(result, indent=2))
        elif args.command == "log":
            for entry in service.log(args.id or None, args.limit):
                print(json.dumps(entry, ensure_ascii=False))
        elif args.command == "tree":
            print(service.tree())
        else:
            result = getattr(service, args.command)()
            print(json.dumps(result, indent=2))
            return 1 if isinstance(result, dict) and result.get("valid") is False else 0
        return 0
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
