"""MCP tools over the same Service the CLI and hooks use. Frames are text; writes are typed."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from pacer.models import Operation
from pacer.service import Service

INSTRUCTIONS = (
    "PACER delivers project context as cards: PAC (work), OVR (source asset), OGM (requirement "
    "with a probe), DEC (decision or latch), NDL (scoped intake). Hooks inject frames at session "
    "start, before and after edits, and at stop; you do not fetch context to begin. Use pacer_q "
    "for any ID, path or #tag; pacer_write for changes (add set link move status latch pace "
    "absorb archive repath); pacer_probe to prove a requirement. Every tool takes the absolute "
    "project root. Cells are bounded; long text belongs in files. The skill `pacer` holds the "
    "grammar and operating rules."
)


def build_server(bound_root: Path | None = None) -> FastMCP:
    """A stdio server; `bound_root` restricts every tool to one project."""
    bound = bound_root.resolve(strict=True) if bound_root else None
    server = FastMCP("pacer", instructions=INSTRUCTIONS, log_level="WARNING")
    read = ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
    )
    write = ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
    )

    def service(root: str) -> Service:
        path = Path(root)
        if not path.is_absolute():
            raise ValueError("Pass the absolute project root")
        path = path.resolve(strict=True)
        if bound is not None and path != bound:
            raise ValueError("That project root is outside this server's binding")
        return Service(path)

    @server.tool(annotations=read)
    def pacer_frame(
        root: str, kind: Literal["session", "edit", "prompt", "stop"], focus: str = ""
    ) -> str:
        """Compile a frame: the session spine, the constraints on a path (`edit`, focus=path),
        the cards a text mentions (`prompt`, focus=text), or the stop gate."""
        return service(root).frame(kind, focus)

    @server.tool(annotations=read)
    def pacer_q(root: str, query: str, limit: int = 40) -> str:
        """Cards for an ID and its neighbours, a project path, a #tag, a register name
        (todo overlord organism nodule decision), or register:STATUS."""
        return service(root).q(query, limit)

    @server.tool(annotations=write)
    def pacer_write(
        root: str, operations: list[Operation], actor: str, preview: bool = False
    ) -> dict[str, object]:
        """Apply operations atomically: add, set, link, move, status, latch, pace, absorb,
        archive, repath. All succeed or none do; each change is appended to the ledger."""
        batch = [op.model_dump(by_alias=True) for op in operations]
        return service(root).write(batch, actor, preview=preview)

    @server.tool(annotations=write)
    def pacer_probe(root: str, id: str, actor: str) -> dict[str, object]:
        """Run a requirement's Probe command, record the evidence cell, return the card."""
        return service(root).probe(id, actor)

    @server.tool(annotations=read)
    def pacer_validate(root: str) -> dict[str, object]:
        """Check every register and reference; warnings list missing files and probes."""
        return service(root).validate()

    @server.tool(annotations=write)
    def pacer_sync(root: str, actor: str, preview: bool = True) -> dict[str, object]:
        """Retire asset rows whose file no longer exists; preview by default."""
        return service(root).sync(actor, preview=preview)

    @server.tool(annotations=read)
    def pacer_log(root: str, id: str = "", limit: int = 20) -> list[dict[str, object]]:
        """Ledger events for an ID, or the newest overall."""
        return service(root).log(id or None, limit)

    @server.tool(annotations=write)
    def pacer_init(root: str, name: str = "", tier: str = "prototype") -> dict[str, object]:
        """Create `.pacer/` with empty registers in a project that has none."""
        return service(root).init(name, tier)

    @server.tool(annotations=write)
    def pacer_migrate(root: str, actor: str, preview: bool = True) -> dict[str, object]:
        """Bring an older PACER project (0.5, 2.0 or root-level 3.0) to the current layout."""
        return service(root).migrate(None, actor=actor, preview=preview)

    @server.tool(annotations=write)
    def pacer_recover(root: str) -> dict[str, object]:
        """Finish a write that was interrupted mid-publication; refuses on outside edits."""
        return service(root).recover()

    return server
