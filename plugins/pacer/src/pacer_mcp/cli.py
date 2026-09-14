"""PACER CLI and stdio entrypoint; diagnostics never contaminate MCP stdout."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pacer_mcp.schema import HEADERS
from pacer_mcp.semantics import semantic_schema
from pacer_mcp.service import Service


def main(argv: list[str] | None = None) -> int:
    """Execute the same service boundary used by MCP and return meaningful exit codes."""
    parser = argparse.ArgumentParser(
        prog="pacer", description="Query and operate PACER's four CSV registers"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Project root (default: cwd)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("initialize", "onboard", "validate", "recover", "schema"):
        sub.add_parser(name)
    server = sub.add_parser("serve", help="Run the official MCP stdio server")
    server.add_argument(
        "--root", dest="serve_root", type=Path, help="Restrict tools to this project"
    )
    query = sub.add_parser("query", help="Query projected rows instead of dumping files")
    query.add_argument("register", choices=HEADERS)
    query.add_argument("--where", action="append", default=[], metavar="COLUMN=VALUE")
    query.add_argument("--fields", help="Comma-separated projection columns")
    query.add_argument("--tag", default="")
    query.add_argument("--ready", action="store_true")
    query.add_argument("--limit", type=int, default=20)
    query.add_argument("--offset", type=int, default=0)
    graph = sub.add_parser("graph")
    graph.add_argument("id")
    graph.add_argument("--depth", type=int, default=1)
    graph.add_argument("--limit", type=int, default=30)
    context = sub.add_parser("context", help="Assemble sufficient task context and a write receipt")
    context.add_argument("id")
    context.add_argument("--max-bytes", type=int, default=32_000)
    evaluate = sub.add_parser("evaluate", help="Evaluate rule and acceptance freshness")
    evaluate.add_argument("id")
    for name in ("apply", "preview", "migrate"):
        command = sub.add_parser(name)
        command.add_argument("--actor", required=True)
        command.add_argument("--revision", required=True)
        command.add_argument("--onboarding", required=True)
        if name == "migrate":
            command.add_argument("--apply", action="store_true", dest="publish")
        else:
            command.add_argument("--file", required=True, type=Path, help="JSON command array file")
            command.add_argument(
                "--context-file", type=Path, help="JSON receipt from pacer context"
            )
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            from pacer_mcp.server import build_server

            build_server(args.serve_root).run(transport="stdio")
            return 0
        service = Service(args.root)
        if args.command == "schema":
            from pydantic import TypeAdapter

            from pacer_mcp.models import Operation

            result = {
                "columns": HEADERS,
                "operations": TypeAdapter(list[Operation]).json_schema(),
                **semantic_schema(),
            }
        elif args.command == "query":
            if any("=" not in value for value in args.where):
                raise ValueError("--where expects COLUMN=VALUE")
            result = service.query(
                args.register,
                where=dict(value.split("=", 1) for value in args.where),
                fields=args.fields.split(",") if args.fields else None,
                tag=args.tag,
                ready=args.ready,
                limit=args.limit,
                offset=args.offset,
            )
        elif args.command == "graph":
            result = service.graph(args.id, depth=args.depth, limit=args.limit)
        elif args.command == "context":
            result = service.context(args.id, max_bytes=args.max_bytes)
        elif args.command == "evaluate":
            result = service.evaluate(args.id)
        elif args.command in {"apply", "preview"}:
            if args.file.stat().st_size > 1_000_000:
                raise ValueError("Command file exceeds 1 MB")
            from pydantic import TypeAdapter

            from pacer_mcp.models import Operation

            operations = TypeAdapter(list[Operation]).validate_json(args.file.read_bytes())
            result = service.apply(
                [op.model_dump(by_alias=True) for op in operations],
                actor=args.actor,
                revision=args.revision,
                onboarding=args.onboarding,
                preview=args.command == "preview",
                context=json.loads(args.context_file.read_text(encoding="utf-8"))
                if args.context_file
                else None,
            )
        elif args.command == "migrate":
            result = service.migrate(
                actor=args.actor,
                revision=args.revision,
                onboarding=args.onboarding,
                preview=not args.publish,
            )
        else:
            result = getattr(service, args.command)()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1 if result.get("valid") is False else 0
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
