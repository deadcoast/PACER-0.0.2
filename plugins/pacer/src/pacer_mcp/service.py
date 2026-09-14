"""Transport-neutral PACER application boundary and onboarding receipts."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from pacer_mcp.commands import Editor
from pacer_mcp.context import build_context, guard_context, operational_nodules
from pacer_mcp.evidence import evaluate_rule, stale_requirements
from pacer_mcp.query import graph, health, next_ids, query_rows
from pacer_mcp.schema import HEADERS, REF_PATTERN, VERSION, contained_path, empty_row, refs, utc_now
from pacer_mcp.store import Store, digest
from pacer_mcp.validation import validate_web


class Service:
    """Expose identical guarded operations to shell users and MCP clients."""

    def __init__(self, root: Path):
        self.store = Store(root)

    def authority(self) -> dict:
        """Fingerprint the real project instructions; a digest is not proof of comprehension."""
        result = {}
        for name in ("README.md", "AGENTS.md"):
            path = contained_path(self.store.root, name)
            if not path.is_file():
                raise ValueError(f"Onboarding requires {name} at the project root")
            result[name] = digest(path.read_bytes())
        return {
            "files": result,
            "onboarding": digest(
                json.dumps(
                    {"profile": VERSION, "root": str(self.store.root), "files": result},
                    sort_keys=True,
                ).encode()
            ),
        }

    def onboard(self) -> dict:
        """Return the session opening queries and exact authority fingerprints."""
        with self.store.locked():
            snapshot = self.store.load()
            return {
                "root": str(self.store.root),
                "format": VERSION,
                **self.authority(),
                "revision": snapshot.revision,
                "health": health(snapshot.tables),
                "ready": query_rows(snapshot.tables, "todo", ready=True),
                "active": query_rows(snapshot.tables, "nodule", where={"Status": "ACTIVE"}),
                "next_ids": next_ids(snapshot.tables),
                "validation": validate_web(snapshot.tables, self.store.root, snapshot.headers),
                "stale_evidence": stale_requirements(snapshot.tables, self.store.root),
                "instructions": "Read this project's README.md then AGENTS.md. Query OVR by Path "
                "before source edits. Pace new scope before building. Use query projections and "
                "pacer_context for the active task. Submit commands with current revision, "
                "onboarding and context receipt. Checkpoint next action; evaluate, refresh and "
                "verify rules. Receipts do not prove understanding; judge DoDs and evidence.",
            }

    def initialize(self) -> dict:
        """Create empty real registers, mapping authority files without copying examples."""
        self.authority()
        with self.store.locked():
            snapshot = self.store.load(missing_ok=True)
            if snapshot.files:
                raise ValueError(
                    "Registers already exist; initialize never overwrites existing work"
                )
            now = utc_now()
            paths = ["README.md", "AGENTS.md"] + [f"{name}.PACER.csv" for name in HEADERS]
            for i, path in enumerate(paths, 1):
                snapshot.tables["overlord"].append(
                    empty_row(
                        "overlord",
                        {
                            "ID": f"OVR-{i:03d}",
                            "AssetType": "FILE",
                            "Path": path,
                            "Purpose": "Project authority or canonical PACER register",
                            "UpdatedAt": now,
                            "Notes": f"{now} initialize: registered project authority",
                            "Tags": "#core",
                        },
                    )
                )
            _require_valid(validate_web(snapshot.tables, self.store.root, snapshot.headers))
            self.store.publish(snapshot, snapshot.encode())
        return self.onboard()

    def validate(self) -> dict:
        """Validate current CSV and cross-file invariants without mutating register data."""
        with self.store.locked():
            snapshot = self.store.load()
            return {
                "revision": snapshot.revision,
                **validate_web(snapshot.tables, self.store.root, snapshot.headers),
                "stale_evidence": stale_requirements(snapshot.tables, self.store.root),
            }

    def context(self, task_id: str, *, max_bytes: int = 32_000) -> dict:
        """Retrieve sufficient operational state for a task, including a freshness receipt."""
        with self.store.locked():
            snapshot = self.store.load()
            return build_context(snapshot.tables, self.store.root, task_id, max_bytes)

    def evaluate(self, row_id: str) -> dict:
        """Evaluate a rule without changing its stored acceptance or source files."""
        with self.store.locked():
            snapshot = self.store.load()
            index = {r["ID"]: r for rows in snapshot.tables.values() for r in rows}
            if row_id not in index or not row_id.startswith("OGM-"):
                raise ValueError(f"REFUSAL: Unknown ID {row_id}")
            return evaluate_rule(index[row_id], index, self.store.root)

    def query(self, register: str, **options) -> dict:
        """Return bounded rows from a consistent locked snapshot."""
        with self.store.locked():
            snapshot = self.store.load()
            return {
                "revision": snapshot.revision,
                **query_rows(snapshot.tables, register, **options),
            }

    def graph(self, row_id: str, *, depth: int = 1, limit: int = 30) -> dict:
        """Retrieve a small connected context neighborhood."""
        with self.store.locked():
            snapshot = self.store.load()
            return {
                "revision": snapshot.revision,
                **graph(snapshot.tables, row_id, depth=depth, limit=limit),
            }

    def apply(
        self,
        operations: list[dict],
        *,
        actor: str,
        revision: str,
        onboarding: str,
        preview: bool = False,
        context: dict | None = None,
    ) -> dict:
        """Apply one atomic logical change after onboarding and revision preconditions."""
        if not actor.strip() or len(actor) > 100 or "\n" in actor:
            raise ValueError("A short single-line actor is required")
        if not 1 <= len(operations) <= 200 or len(json.dumps(operations)) > 1_000_000:
            raise ValueError("Batch must contain 1..200 operations and at most 1 MB")
        with self.store.locked():
            snapshot = self.store.load()
            if revision != snapshot.revision:
                raise ValueError("Stale revision; query the current web before applying")
            if onboarding != self.authority()["onboarding"]:
                raise ValueError("Stale onboarding; reread README.md and AGENTS.md")
            guard_context(snapshot.tables, self.store.root, operations, context)
            before_tables = deepcopy(snapshot.tables)
            editor = Editor(snapshot.tables, actor, self.store.root)
            for operation in operations:
                try:
                    editor.execute(operation)
                except (KeyError, TypeError, AttributeError) as exc:
                    raise ValueError(
                        f"Malformed {operation.get('op', 'unknown')} command: {exc}"
                    ) from exc
            editor.reconcile()
            guard_context(before_tables, self.store.root, operations, context, snapshot.tables)
            index = {r["ID"]: r for rows in snapshot.tables.values() for r in rows}
            for operation in operations:
                if operation.get("op") == "verify":
                    _, verified = editor.find(operation["id"])
                    if evaluate_rule(verified, index, self.store.root)["freshness"] != "CURRENT":
                        raise ValueError(
                            "Verified basis changed during batch; retrieve context and verify again"
                        )
                if operation.get("op") == "absorb" or (
                    operation.get("op") == "transition" and operation.get("status") == "DONE"
                ):
                    accepted = index[operation["id"]]
                    if operational_nodules(accepted, index):
                        field = "OGMTargets" if operation["op"] == "absorb" else "OGMRefs"
                        for target in refs(accepted.get(field, "")):
                            if (
                                index[target]["Status"] != "VALIDATED_COMPLETE"
                                or evaluate_rule(index[target], index, self.store.root)["freshness"]
                                != "CURRENT"
                            ):
                                raise ValueError(
                                    f"Final acceptance requires current verified rule {target}"
                                )
            report = validate_web(snapshot.tables, self.store.root, snapshot.headers)
            _require_valid(report)
            after = snapshot.encode()
            changed_files = [
                k
                for k in sorted(set(after) | set(snapshot.files))
                if after.get(k) != snapshot.files.get(k)
            ]
            result = {
                "preview": preview,
                "changed_ids": sorted(editor.changed),
                "changed_files": changed_files,
                "validation": report,
            }
            if preview:
                return {**result, "revision": snapshot.revision}
            return {**result, "revision": self.store.publish(snapshot, after)}

    def migrate(self, *, actor: str, revision: str, onboarding: str, preview: bool = True) -> dict:
        """Add profile columns and reciprocal refs without losing legacy or custom cells."""
        with self.store.locked():
            snapshot = self.store.load()
            if revision != snapshot.revision or onboarding != self.authority()["onboarding"]:
                raise ValueError("Stale revision or onboarding")
            editor = Editor(snapshot.tables, actor, legacy_migration=True)
            for register, rows in snapshot.tables.items():
                snapshot.headers[register].extend(
                    k for k in HEADERS[register] if k not in snapshot.headers[register]
                )
                for row in rows:
                    for key in HEADERS[register]:
                        row.setdefault(key, "")
                    if register == "todo":
                        for prefix, field in (
                            ("OVR", "OVRRefs"),
                            ("OGM", "OGMRefs"),
                            ("NDL", "NDLRefs"),
                        ):
                            values = [
                                r
                                for r in REF_PATTERN.findall(row["RelatedWork"])
                                if r.startswith(prefix + "-")
                            ]
                            row[field] = ";".join(
                                dict.fromkeys(row[field].split(";") + values)
                            ).strip(";")
                    if register == "nodule":
                        row["Lane"] = row["Lane"] or row["NoduleName"] or row["ID"]
                    if register == "organism":
                        row["Authority"] = row["Authority"] or "LEGACY"
                    editor.note(
                        row, f"migrated to executable profile {VERSION}; original cells retained"
                    )
            editor.reconcile()
            report = validate_web(snapshot.tables, self.store.root, snapshot.headers)
            _require_valid(report)
            if preview:
                return {"preview": True, "revision": snapshot.revision, "validation": report}
            return {
                "preview": False,
                "revision": self.store.publish(snapshot, snapshot.encode()),
                "validation": report,
            }

    def recover(self) -> dict:
        """Explicitly resume a known interrupted publication under the writer lock."""
        with self.store.locked():
            return self.store.recover()


def _require_valid(report: dict) -> None:
    if not report["valid"]:
        raise ValueError(report["errors"][0])
