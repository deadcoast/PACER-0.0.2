"""MCP tools over the same Service. Frames are text; writes are typed."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from pacer_mcp.models import Operation
from pacer_mcp.service import Service

INSTRUCTIONS = (
    "PACER 3 delivers project context as cards: PAC (work), OVR (source), OGM (requirement+probe), "
    "DEC (decision/latch), NDL (intake). Hooks inject frames at session start, before/after edits "
    "and at stop. Use pacer_q for any ID, path or #tag; pacer_write for the lexicon "
    "(add/set/link/move/status/latch/pace/absorb); pacer_probe to run a requirement's Probe. "
    "Cells are bounded; long text belongs in files."
)


def build_server(bound_root: Path | None = None) -> FastMCP:
    """Build a stdio server; an optional project binding restricts every tool's root."""
    bound = bound_root.resolve(strict=True) if bound_root else None
    server = FastMCP("PACER", instructions=INSTRUCTIONS, log_level="WARNING")
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
        if bound is not None and path != bound:
            raise ValueError("Project root is outside this server's binding")
        return Service(path)

    @server.tool(annotations=read)
    def pacer_frame(
        root: str, kind: Literal["session", "edit", "prompt", "stop"], focus: str = ""
    ) -> str:
        """Compile a bounded card frame: session spine, edit constraints for a path, prompt
        mentions, or the stop gate."""
        return service(root).frame(kind, focus)

    @server.tool(annotations=read)
    def pacer_q(root: str, query: str, limit: int = 40) -> str:
        """Cards for an ID (with neighbours), a repo path, a #tag, a register, or
        register:STATUS."""
        return service(root).q(query, limit)

    @server.tool(annotations=write)
    def pacer_write(
        root: str, operations: list[Operation], actor: str, preview: bool = False
    ) -> dict[str, object]:
        """Apply add/set/link/move/status/latch/pace/absorb atomically; every change is
        ledgered."""
        return service(root).write(
            [op.model_dump(by_alias=True) for op in operations], actor, preview=preview
        )

    @server.tool(annotations=write)
    def pacer_probe(root: str, id: str, actor: str) -> dict[str, object]:
        """Run an OGM's Probe command, record its evidence cell and return the updated card."""
        return service(root).probe(id, actor)

    @server.tool(annotations=read)
    def pacer_validate(root: str) -> dict[str, object]:
        """Validate every register and cross-reference."""
        return service(root).validate()

    @server.tool(annotations=write)
    def pacer_initialize(root: str) -> dict[str, object]:
        """Create empty PACER 3 registers; never overwrites."""
        return service(root).initialize()

    @server.tool(annotations=write)
    def pacer_migrate(
        root: str, source: Literal["0.5", "v2"], actor: str, preview: bool = True
    ) -> dict[str, object]:
        """Migrate profile 0.5 CSV registers or a v2 todo.PACER plan; preview by default."""
        return service(root).migrate(source, actor=actor, preview=preview)

    @server.tool(annotations=read)
    def pacer_log(root: str, id: str = "", limit: int = 20) -> list[dict[str, object]]:
        """Ledger events for an ID (or the newest overall)."""
        return service(root).log(id or None, limit)

    @server.tool(annotations=write)
    def pacer_recover(root: str) -> dict[str, object]:
        """Complete an interrupted register publication; refuse conflicting edits."""
        return service(root).recover()

    return server
