"""Transport-neutral application boundary: frames in, events out."""

from __future__ import annotations

from pathlib import Path

from pacer_mcp.commands import Editor
from pacer_mcp.frames import active_pace, edit_frame, prompt_frame, render, session_frame
from pacer_mcp.gates import edit_decision, stop_decision
from pacer_mcp.probe import run_probe
from pacer_mcp.provider import select_provider
from pacer_mcp.rank import rank
from pacer_mcp.schema import (
    HEADERS,
    REF_PATTERN,
    REGISTERS,
    TAG_PATTERN,
    VERSION,
    contained_path,
    empty_row,
    refs,
    utc_now,
)
from pacer_mcp.spec import read_spec
from pacer_mcp.store import Store, encode_csv, parse_csv
from pacer_mcp.validation import validate_web


class Service:
    """Expose identical operations to the CLI, the hooks and the MCP server."""

    def __init__(self, root: Path):
        self.store = Store(root)
        self.root = self.store.root
        self.spec = read_spec(self.root)
        self._provider = None

    @property
    def provider(self):
        if self._provider is None:
            self._provider = select_provider(self.root, self.spec["provider"])
        return self._provider

    # -- reads ---------------------------------------------------------------
    def frame(self, kind: str, focus: str = "") -> str:
        with self.store.locked():
            t = self.store.load().tables
            if kind == "session":
                return session_frame(t, self.root, self.store, self.provider, self.spec)
            if kind == "edit":
                return edit_frame(t, self.root, self.store, self.provider, self.spec, focus)
            if kind == "prompt":
                return prompt_frame(t, self.root, self.provider, self.spec, focus)
            if kind == "stop":
                return stop_decision(t, self.root, self.store, self.provider, self.spec)["text"]
            raise ValueError("frame kind must be session, edit, prompt or stop")

    def q(self, query: str, limit: int = 40) -> str:
        """Cards for an ID (plus neighbours), a #tag, a register, register:STATUS or a path."""
        with self.store.locked():
            t = self.store.load().tables
            index = {r["ID"]: reg for reg in REGISTERS for r in t[reg]}
            query = query.strip()
            if REF_PATTERN.fullmatch(query) and query in index:
                keys = [k for d, k in rank(t, self.provider, [query]) if d <= 2]
            elif TAG_PATTERN.fullmatch(query):
                keys = [
                    r["ID"]
                    for reg in REGISTERS
                    for r in t[reg]
                    if query in r.get("Tags", "").split()
                ]
            elif ":" in query and query.split(":")[0] in REGISTERS:
                reg, status = query.split(":", 1)
                keys = [r["ID"] for r in t[reg] if r.get("Status") == status]
            elif query in REGISTERS:
                keys = [r["ID"] for r in t[query]]
            else:
                keys = [r["ID"] for r in t["overlord"] if r.get("Path") == query]
                if not keys:
                    return edit_frame(t, self.root, self.store, self.provider, self.spec, query)
            lines = [render(k, t, self.root, self.provider) for k in keys[:limit]]
            if len(keys) > limit:
                lines.append(f"+{len(keys) - limit} more")
            return "\n".join(lines)

    def log(self, row_id: str | None, limit: int = 20) -> list[dict]:
        return self.store.ledger_read(row_id, limit)

    def validate(self) -> dict:
        with self.store.locked():
            snap = self.store.load()
            return {"revision": snap.revision, **validate_web(snap.tables, self.root, snap.headers)}

    def edit_decision(self, path: str) -> dict:
        with self.store.locked():
            t = self.store.load().tables
            return edit_decision(t, self.root, self.store, self.spec, path)

    def tree(self) -> str:
        from pacer_mcp.tree import render_tree

        with self.store.locked():
            return render_tree(self.store.load().tables, self.spec)

    # -- writes --------------------------------------------------------------
    def write(self, operations: list[dict], actor: str, preview: bool = False) -> dict:
        """Apply a batch atomically; publish the CSVs, then append the events."""
        if not actor.strip() or "\n" in actor or len(actor) > 100:
            raise ValueError("A short single-line actor is required")
        if not 1 <= len(operations) <= 200:
            raise ValueError("Batch must contain 1..200 operations")
        with self.store.locked():
            snap = self.store.load()
            editor = Editor(snap.tables, actor, self.root)
            for op in operations:
                try:
                    editor.execute(op)
                except (KeyError, TypeError, AttributeError) as exc:
                    raise ValueError(f"Malformed {op.get('op', 'unknown')} command: {exc}") from exc
            report = validate_web(snap.tables, self.root, snap.headers)
            if not report["valid"]:
                raise ValueError(report["errors"][0])
            result = {
                "preview": preview,
                "changed_ids": sorted(editor.changed),
                "validation": report,
                "events": len(editor.events),
            }
            if preview:
                return {**result, "revision": snap.revision}
            revision = self.store.publish(snap, snap.encode())
            for event in editor.events:
                self.store.ledger_append(event)
            return {**result, "revision": revision}

    def probe(self, row_id: str, actor: str) -> dict:
        with self.store.locked():
            snap = self.store.load()
            row = next((r for r in snap.tables["organism"] if r["ID"] == row_id), None)
            if row is None:
                raise ValueError(f"REFUSAL: Unknown ID {row_id}")
            result = run_probe(row, snap.tables, self.root, actor)
            row["Evidence"] = result["evidence"]
            report = validate_web(snap.tables, self.root, snap.headers)
            if not report["valid"]:
                raise ValueError(report["errors"][0])
            self.store.publish(snap, snap.encode())
            self.store.ledger_append(
                {"actor": actor, "op": "probe", "id": row_id, "detail": result}
            )
            return {
                "id": row_id,
                **result,
                "card": render(row_id, snap.tables, self.root, self.provider),
            }

    def touch(self, path: str, actor: str) -> str:
        """Record an edit against the active pace; register unknown paths."""
        with self.store.locked():
            snap = self.store.load()
            pace = active_pace(snap.tables, self.store)
            editor = Editor(snap.tables, actor, self.root)
            editor.execute({"op": "touch", "path": path, "pace": pace["ID"] if pace else ""})
            report = validate_web(snap.tables, self.root, snap.headers)
            if not report["valid"]:
                return f"touch refused: {report['errors'][0]}"
            self.store.publish(snap, snap.encode())
            for event in editor.events:
                self.store.ledger_append(event)
            new = next((e["detail"].get("new") for e in editor.events if e["op"] == "touch"), None)
            bound_here = {r["ID"] for r in snap.tables["overlord"] if r["Path"] == path}
            stale = [
                r["ID"]
                for r in snap.tables["organism"]
                if r.get("Evidence") and set(refs(r.get("Binds", ""))) & bound_here
            ]
            parts = [f"{new} registered #unpurposed" if new else f"touched {path}"]
            if stale:
                parts.append("stale: " + ", ".join(stale))
            return " | ".join(parts)

    def stop(self, actor: str) -> dict:
        with self.store.locked():
            snap = self.store.load()
            decision = stop_decision(snap.tables, self.root, self.store, self.provider, self.spec)
            pace = active_pace(snap.tables, self.store)
            if pace and pace.get("Next") != decision["next"]:
                pace["Next"] = decision["next"]
                self.store.publish(snap, snap.encode())
                self.store.ledger_append(
                    {
                        "actor": actor,
                        "op": "checkpoint",
                        "id": pace["ID"],
                        "detail": {"next": decision["next"]},
                    }
                )
            return decision

    def initialize(self) -> dict:
        with self.store.locked():
            snap = self.store.load(missing_ok=True)
            if snap.files:
                raise ValueError("Registers already exist; initialize never overwrites")
            for name in ("README.md", "AGENTS.md"):
                if contained_path(self.root, name).is_file():
                    snap.tables["overlord"].append(
                        empty_row(
                            "overlord",
                            {
                                "ID": f"OVR-{len(snap.tables['overlord']) + 1:03d}",
                                "Path": name,
                                "Kind": "FILE",
                                "Purpose": "project authority",
                                "Tags": "#core",
                            },
                        )
                    )
            self.store.publish(snap, snap.encode())
            self.store.ledger_append(
                {
                    "actor": "initialize",
                    "op": "initialize",
                    "id": "-",
                    "detail": {"version": VERSION, "at": utc_now()},
                }
            )
        return self.validate()

    def recover(self) -> dict:
        with self.store.locked():
            return self.store.recover()

    def migrate(self, source: str, *, actor: str, preview: bool = True) -> dict:
        """Migrate profile 0.5 registers or a v2 plan into PACER 3; preview by default."""
        import shutil

        from pacer_mcp.migrate import from_05, from_v2

        with self.store.locked():
            if source == "0.5":
                old, sizes = {}, {}
                for name in ("todo", "overlord", "organism", "nodule"):
                    path = contained_path(self.root, f"{name}.PACER.csv")
                    data = path.read_bytes()
                    sizes[name] = len(data)
                    columns, old[name] = parse_csv(data, name)
                    if name == "todo" and "Kind" in columns:
                        raise ValueError("Registers already use PACER 3 columns")
                archived = []
                archive = contained_path(self.root, "archive/nodules")
                if archive.exists():
                    for path in sorted(archive.glob("*.PACER.csv")):
                        archived += parse_csv(path.read_bytes(), path.name)[1]
                tables, events = from_05(old, archived, self.spec["tier"], self.root)
            elif source == "v2":
                text = contained_path(self.root, "todo.PACER").read_text(encoding="utf-8")
                sizes = {"todo.PACER": len(text.encode("utf-8"))}
                tables, events = from_v2(text, self.root)
            else:
                raise ValueError("source must be 0.5 or v2")
            report = validate_web(tables, self.root)
            encoded = {}
            for register in REGISTERS:
                live = [
                    r
                    for r in tables[register]
                    if not (register == "nodule" and r["Status"] == "ABSORBED")
                ]
                encoded[f"{register}.PACER.csv"] = encode_csv(HEADERS[register], live)
            result = {
                "preview": preview,
                "sizes_before": sizes,
                "sizes_after": {k: len(v) for k, v in encoded.items()},
                "counts": {k: len(v) for k, v in tables.items()},
                "validation": report,
                "ledger_events": len(events),
            }
            if preview or not report["valid"]:
                return result
            if source == "0.5":
                old_dir = contained_path(self.root, "archive/pacer-0.5")
                old_dir.mkdir(parents=True, exist_ok=True)
                for name in ("todo", "overlord", "organism", "nodule"):
                    shutil.move(
                        str(contained_path(self.root, f"{name}.PACER.csv")),
                        str(old_dir / f"{name}.PACER.csv"),
                    )
                if archive.exists():
                    shutil.move(str(archive), str(old_dir / "nodules"))
            for name, data in encoded.items():
                contained_path(self.root, name).write_bytes(data)
            for row in tables["nodule"]:
                if row["Status"] == "ABSORBED":
                    target = contained_path(self.root, f"archive/nodules/{row['ID']}.PACER.csv")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(encode_csv(HEADERS["nodule"], [row]))
            for event in events:
                self.store.ledger_append(event)
            self.store.ledger_append(
                {
                    "actor": actor,
                    "op": "migrate",
                    "id": "-",
                    "detail": {"from": source, "counts": result["counts"]},
                }
            )
        return {**result, "validation": self.validate()}
