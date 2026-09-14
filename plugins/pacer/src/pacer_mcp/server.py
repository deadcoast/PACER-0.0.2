"""Official MCP SDK tools, resources and prompt for the PACER workflow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from pacer_mcp.models import ContextReceipt, Operation
from pacer_mcp.schema import HEADERS, OGM_STATUSES, PAIRS, REF_FIELDS, TODO_TRANSITIONS, VERSION
from pacer_mcp.semantics import semantic_schema
from pacer_mcp.service import Service


def build_server(bound_root: Path | None = None) -> FastMCP:
    """Build a stdio server; an optional project binding restricts every tool's root."""
    bound_root = bound_root.resolve(strict=True) if bound_root else None
    server = FastMCP(
        "PACER",
        instructions=(
            "PACER is the project's operational context. Onboard with the absolute project root; "
            "Read authority entry points. Pace original wording and explicit rules. "
            "Retrieve pacer_context for the PAC before acting; never omit mandatory context. "
            "Apply with current revision, onboarding and context receipt. Checkpoint next_action. "
            "Evaluate and verify rules against source; refresh stale evidence before completion. "
            "Query OVR paths before edits. Plugin cwd is not the project root."
        ),
        log_level="WARNING",
    )
    read = ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
    )
    write = ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
    )

    def service(root: str) -> Service:
        path = Path(root)
        if not path.is_absolute():
            raise ValueError("Pass the absolute project root explicitly")
        path = path.resolve(strict=True)
        if bound_root is not None and path != bound_root:
            raise ValueError("Project root is outside this server's binding")
        return Service(path)

    @server.tool(annotations=read)
    def pacer_onboard(root: str) -> dict[str, object]:
        """Start a session with authority hashes, ready work, health, active growth and next IDs."""
        return service(root).onboard()

    @server.tool(annotations=read)
    def pacer_query(
        root: str,
        register: Literal["todo", "overlord", "organism", "nodule"],
        where: dict[str, str] | None = None,
        fields: list[str] | None = None,
        tag: str = "",
        ready: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, object]:
        """Retrieve bounded rows by columns, path, status, tag or hard-gated readiness."""
        return service(root).query(
            register, where=where, fields=fields, tag=tag, ready=ready, limit=limit, offset=offset
        )

    @server.tool(annotations=read)
    def pacer_graph(root: str, id: str, depth: int = 1, limit: int = 30) -> dict[str, object]:
        """Follow a bounded cross-register reference neighborhood around an existing ID."""
        return service(root).graph(id, depth=depth, limit=limit)

    @server.tool(annotations=read)
    def pacer_context(root: str, id: str, max_bytes: int = 32_000) -> dict[str, object]:
        """Load task context, typed rules, source freshness, checkpoint delta and receipt."""
        return service(root).context(id, max_bytes=max_bytes)

    @server.tool(annotations=read)
    def pacer_evaluate(root: str, id: str) -> dict[str, object]:
        """Evaluate an OGM rule and inspect exact source bindings without changing acceptance."""
        return service(root).evaluate(id)

    @server.tool(annotations=read)
    def pacer_schema(register: str = "") -> dict[str, object]:
        """Inspect literal columns, typed refs, reciprocal links and legal status transitions."""
        if register and register not in HEADERS:
            raise ValueError("Unknown register")
        return {
            "version": VERSION,
            "columns": {register: HEADERS[register]} if register else HEADERS,
            "references": {register: REF_FIELDS[register]} if register else REF_FIELDS,
            "reciprocal_pairs": PAIRS,
            "task_transitions": sorted(TODO_TRANSITIONS),
            "organism_statuses": sorted(OGM_STATUSES),
            **semantic_schema(),
        }

    @server.tool(annotations=read)
    def pacer_validate(root: str) -> dict[str, object]:
        """Check CSV, dependencies, source paths, evidence and all cross-register references."""
        return service(root).validate()

    @server.tool(annotations=write)
    def pacer_initialize(root: str) -> dict[str, object]:
        """Initialize absent registers only after project README.md and AGENTS.md exist."""
        return service(root).initialize()

    @server.tool(annotations=read)
    def pacer_preview(
        root: str,
        operations: list[Operation],
        actor: str,
        revision: str,
        onboarding: str,
        context: ContextReceipt | None = None,
    ) -> dict[str, object]:
        """Validate a candidate command batch and return affected IDs/files without publishing."""
        return service(root).apply(
            [op.model_dump(by_alias=True) for op in operations],
            actor=actor,
            revision=revision,
            onboarding=onboarding,
            preview=True,
            context=context.model_dump() if context else None,
        )

    @server.tool(annotations=write)
    def pacer_apply(
        root: str,
        operations: list[Operation],
        actor: str,
        revision: str,
        onboarding: str,
        context: ContextReceipt | None = None,
    ) -> dict[str, object]:
        """Publish a validated PACER command batch using one applying writer and revision checks."""
        return service(root).apply(
            [op.model_dump(by_alias=True) for op in operations],
            actor=actor,
            revision=revision,
            onboarding=onboarding,
            context=context.model_dump() if context else None,
        )

    @server.tool(annotations=write)
    def pacer_migrate(
        root: str, actor: str, revision: str, onboarding: str, preview: bool = True
    ) -> dict[str, object]:
        """Upgrade missing legacy profile columns and reciprocal refs; preview by default."""
        return service(root).migrate(
            actor=actor, revision=revision, onboarding=onboarding, preview=preview
        )

    @server.tool(annotations=write)
    def pacer_recover(root: str) -> dict[str, object]:
        """Complete a known interrupted register publication; refuse conflicting external edits."""
        return service(root).recover()

    @server.resource("pacer://schema")
    def schema_resource() -> str:
        return json.dumps(pacer_schema())

    @server.resource("pacer://schema/{register}")
    def register_schema(register: str) -> str:
        return json.dumps(pacer_schema(register))

    @server.prompt()
    def pacer_onboarding(root: str) -> str:
        """Read project authority and query the four connected organs before development."""
        return (
            f"Work in {root}. Read README.md, then AGENTS.md. Call pacer_onboard with this "
            "absolute root. Query ready todo rows, organism health and ACTIVE nodules. "
            "Before editing any source file query overlord by Path; register new assets "
            "with the source change. Pace the user's request in a nodule; preserve PACER's "
            "source-defined meanings and use typed commands for all register mutations."
        )

    return server
