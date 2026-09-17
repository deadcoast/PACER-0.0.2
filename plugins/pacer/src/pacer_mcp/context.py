"""Compile sufficient operational context and durable checkpoint deltas."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from pacer_mcp.evidence import evaluate_rule, register_path, source_digest
from pacer_mcp.schema import VERSION, hard_blockers, refs
from pacer_mcp.semantics import canonical, fingerprint, typed_edges

CONTEXT_COLUMNS = {
    "todo": [
        "ID",
        "Status",
        "DoD",
        "BlockedBy",
        "DependencyType",
        "OVRRefs",
        "OGMRefs",
        "Title",
        "Context",
        "Instructions",
        "ValidationCriteria",
        "ExpectedOutput",
        "ErrorHandling",
        "DependencyReason",
        "UnblockingStrategy",
        "NextAction",
        "PreviousAttempts",
        "LearningNotes",
        "ApprovalState",
        "ApprovalEvidence",
        "ApprovalActor",
        "ApprovedAt",
        "ApprovalBasis",
    ],
    "overlord": [
        "ID",
        "AssetType",
        "Path",
        "Symbol",
        "Exports",
        "Imports",
        "Requires",
        "RequiredBy",
    ],
    "organism": [
        "ID",
        "Status",
        "Authority",
        "RuleType",
        "RuleSubject",
        "RuleSelector",
        "RuleValue",
        "OVRRefs",
        "BlockedByOGM",
        "OriginText",
        "Requirement",
    ],
    "nodule": [
        "ID",
        "Status",
        "ContextPolicy",
        "UserRequest",
        "TargetOVR",
        "NewAssets",
        "Intent",
        "AbsorptionCriteria",
        "OGMTargets",
        "SpawnedPACs",
    ],
}


def operational_nodules(row: dict, index: dict) -> set[str]:
    """Return the explicitly governed scopes associated with a row."""
    candidates = refs(row.get("NDLRefs", ""))
    if row.get("ID", "").startswith("NDL-"):
        candidates.append(row["ID"])
    return {key for key in candidates if index.get(key, {}).get("ContextPolicy") == "REQUIRED"}


def required_closure(tables: dict, task_id: str) -> tuple[set[str], set[str]]:
    """Close hard work dependencies, admitted scope, source dependencies and reverse impact."""
    index = {r["ID"]: r for rows in tables.values() for r in rows}
    if task_id not in index or not task_id.startswith("PAC-"):
        raise ValueError(f"REFUSAL: Unknown ID {task_id}")
    required, pending, impacted = set(), [task_id], set()

    def admit_impact(keys):
        queue = list(keys)
        while queue:
            target = queue.pop()
            if target in impacted:
                continue
            if target not in index:
                raise ValueError(f"REFUSAL: Unknown ID {target}")
            impacted.add(target)
            pending.append(target)
            queue.extend(refs(index[target].get("RequiredBy", "")))

    while pending:
        key = pending.pop()
        if key in required:
            continue
        row = index.get(key)
        if row is None:
            raise ValueError(f"REFUSAL: Unknown ID {key}")
        required.add(key)
        if key.startswith("PAC-"):
            admit_impact(refs(row.get("OVRRefs", "")))
            pending.extend(hard_blockers(row))
            fields: tuple[str, ...] = ("OVRRefs", "OGMRefs", "NDLRefs")
        elif key.startswith("NDL-"):
            admit_impact(refs(row.get("TargetOVR", "")))
            fields = ("TargetOVR", "OGMTargets", "SpawnedPACs")
        elif key.startswith("OGM-"):
            admit_impact(refs(row.get("OVRRefs", "")))
            pending.extend(
                r["ID"] for r in tables["organism"] if key in refs(r.get("BlockedByOGM", ""))
            )
            fields = ("OVRRefs", "BlockedByOGM", "RuleSubject", "EvidenceArtifact")
        else:
            fields = ("Requires", "OGMRefs")
        for field in fields:
            pending.extend(refs(row.get(field, "")))
    return required, impacted


def context_snapshot(tables: dict, root: Path, task_id: str) -> dict:
    """Bind required row meaning and source bytes without self-referential checkpoint state."""
    required, impacted = required_closure(tables, task_id)
    index = {r["ID"]: r for rows in tables.values() for r in rows}
    row_hashes, sources = {}, {}
    for key in sorted(required):
        row = index[key]
        row_hashes[key] = fingerprint(
            {k: v for k, v in row.items() if k not in {"Notes", "UpdatedAt", "ContextCheckpoint"}}
        )
        if key.startswith("OVR-") and not register_path(row["Path"]):
            sources[row["Path"]] = source_digest(root, row["Path"])
    return {"task": task_id, "rows": row_hashes, "sources": sources, "impacted": sorted(impacted)}


def context_receipt(snapshot: dict, root: Path) -> dict:
    """Issue a freshness precondition; it is not proof that a model understood the packet."""
    authority = {name: source_digest(root, name) for name in ("README.md", "AGENTS.md")}
    return {
        "task": snapshot["task"],
        "root": str(root.resolve()),
        "basis": fingerprint({"profile": VERSION, "authority": authority, **snapshot}),
    }


def compact_context(packet: dict) -> dict:
    """Encode directed edges with shared ID and relation dictionaries without dropping facts."""
    if "encoding" in packet:
        raise ValueError("context is already encoded")
    result = deepcopy(packet)
    ids = packet["required_ids"]
    if len(ids) != len(set(ids)):
        raise ValueError("context IDs must be unique")
    positions = {key: number for number, key in enumerate(ids)}
    kinds = sorted({edge["relation"] for edge in packet["relations"]})
    relations = {key: number for number, key in enumerate(kinds)}
    edges = []
    for edge in packet["relations"]:
        if set(edge) != {"source", "relation", "target"}:
            raise ValueError("context edge has unknown fields")
        edges.append(
            [positions[edge["source"]], relations[edge["relation"]], positions[edge["target"]]]
        )
    result["relations"] = {"kinds": kinds, "edges": edges}
    result["encoding"] = "pacer-context/2"
    return result


def expand_context(packet: dict) -> dict:
    """Decode the versioned edge representation; reject malformed indexes instead of guessing."""
    result = deepcopy(packet)
    if "encoding" not in result:
        return result
    if result.pop("encoding") != "pacer-context/2":
        raise ValueError("Unsupported context encoding")
    try:
        ids, relation = result["required_ids"], result["relations"]
        kinds, encoded = relation["kinds"], relation["edges"]
        if set(relation) != {"kinds", "edges"} or not all(
            isinstance(v, list) for v in (ids, kinds, encoded)
        ):
            raise ValueError
        if (
            any(not isinstance(v, str) for v in ids + kinds)
            or len(ids) != len(set(ids))
            or len(kinds) != len(set(kinds))
        ):
            raise ValueError
        edges = []
        for edge in encoded:
            if not isinstance(edge, list) or len(edge) != 3:
                raise ValueError
            if any(
                type(i) is not int or not 0 <= i < len(dictionary)
                for i, dictionary in zip(edge, (ids, kinds, ids), strict=True)
            ):
                raise ValueError
            edges.append(
                {"source": ids[edge[0]], "relation": kinds[edge[1]], "target": ids[edge[2]]}
            )
        result["relations"] = edges
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid compact context relation encoding") from exc
    return result


def build_context(
    tables: dict, root: Path, task_id: str, max_bytes: int = 32_000, *, encoding: str = "compact"
) -> dict:
    """Return all required context in columnar form or an explicit budget failure."""
    if not 256 <= max_bytes <= 1_000_000:
        raise ValueError("Context max_bytes must be 256..1000000")
    if encoding not in {"compact", "expanded"}:
        raise ValueError("context encoding must be compact or expanded")
    snapshot = context_snapshot(tables, root, task_id)
    required = set(snapshot["rows"])
    index = {r["ID"]: r for rows in tables.values() for r in rows}
    task = index[task_id]
    diagnostics = [
        {"code": "missing_source", "path": path}
        for path, value in snapshot["sources"].items()
        if value is None
    ]
    selected = {}
    for register, columns in CONTEXT_COLUMNS.items():
        rows = [r for r in tables[register] if r["ID"] in required]
        if not rows:
            continue
        used = [field for field in columns if field == "ID" or any(r.get(field) for r in rows)]
        selected[register] = {
            "columns": used,
            "rows": [
                [r.get(field, "") for field in used] for r in sorted(rows, key=lambda r: r["ID"])
            ],
        }
    rules = [
        evaluate_rule(index[key], index, root) for key in sorted(required) if key.startswith("OGM-")
    ]
    for rule in rules:
        rule.pop("basis")
        rule.pop("sources")
        if rule["result"] == "UNRESOLVED":
            diagnostics.append({"code": "unresolved_rule", "id": rule["id"]})
        if rule["freshness"] == "STALE":
            diagnostics.append({"code": "stale_evidence", "id": rule["id"]})
    saved = json.loads(task.get("ContextCheckpoint") or "{}")
    delta = {
        "baseline": bool(saved),
        "changed_rows": sorted(
            key
            for key, value in snapshot["rows"].items()
            if saved.get("rows", {}).get(key) != value
        ),
        "removed_rows": sorted(set(saved.get("rows", {})) - required),
        "changed_sources": sorted(
            path
            for path, value in snapshot["sources"].items()
            if saved.get("sources", {}).get(path) != value
        ),
        "removed_sources": sorted(set(saved.get("sources", {})) - set(snapshot["sources"])),
    }
    complete = not any(d["code"] == "missing_source" for d in diagnostics)
    packet = {
        "profile": VERSION,
        "task": task_id,
        "complete": complete,
        "required_ids": sorted(required),
        "tables": selected,
        "relations": [
            edge
            for edge in typed_edges(tables)
            if edge["source"] in required and edge["target"] in required
        ],
        "sources": snapshot["sources"],
        "impacted": snapshot["impacted"],
        "rules": rules,
        "diagnostics": diagnostics,
        "next_action": task.get("NextAction") or "inspect",
        "delta": delta,
        "receipt": context_receipt(snapshot, root) if complete else None,
    }
    if encoding == "compact":
        packet = compact_context(packet)
    packet["required_bytes"] = 0
    for _ in range(3):
        packet["required_bytes"] = len(canonical(packet).encode("utf-8"))
    if packet["required_bytes"] > max_bytes:
        return {
            "profile": VERSION,
            "task": task_id,
            "complete": False,
            "tables": {},
            "receipt": None,
            "required_count": len(required),
            "required_bytes": packet["required_bytes"],
            "diagnostics": [{"code": "context_budget", "max_bytes": max_bytes}],
        }
    return packet


def guard_context(
    tables: dict,
    root: Path,
    operations: list[dict],
    receipt: dict | None,
    candidate: dict | None = None,
) -> None:
    """Require a current task context for mutations of explicitly operational scope."""
    index = {r["ID"]: r for rows in tables.values() for r in rows}
    paced = [
        op
        for op in operations
        if op.get("op") == "pace" and op.get("nodule", {}).get("ContextPolicy") == "REQUIRED"
    ]
    if paced:
        if len(operations) != 1:
            raise ValueError("Retrieve task context after pace before operational work")
        # Intake alone creates the scope from which a first receipt can be obtained.
        return
    governed, targets = set(), set()
    for operation in operations:
        if operation.get("op") == "pace":
            continue
        row = index.get(operation.get("id", ""), operation.get("row", {}))
        governed.update(operational_nodules(row, index))
        if row.get("ID"):
            targets.add(row["ID"])
    if candidate is not None:
        proposed = {r["ID"]: r for rows in candidate.values() for r in rows}
        for key, row in proposed.items():
            if row != index.get(key):
                if (
                    len(operations) == 1
                    and operations[0].get("op") == "refresh"
                    and key.startswith("OGM-")
                    and receipt is not None
                ):
                    required, _ = required_closure(tables, receipt["task"])
                    if key not in required:
                        raise ValueError(f"Refresh target outside task context: {key}")
                    # Refresh only records observed failures/freshness; it cannot change
                    # another lane's meaning, scope or source. Its full affected set is read.
                    continue
                fields = {field for field in row if row[field] != index.get(key, {}).get(field)}
                # A declared source edge maintains its inverse without granting semantic
                # write access to the dependency's lane. A receipt is still mandatory.
                if (
                    receipt is not None
                    and key.startswith("OVR-")
                    and fields <= {"RequiredBy", "Notes", "UpdatedAt"}
                ):
                    continue
                targets.add(key)
                governed.update(operational_nodules(row, proposed))
                governed.update(operational_nodules(index.get(key, {}), index))
    if not governed and receipt is None:
        return
    if not isinstance(receipt, dict) or not isinstance(receipt.get("task"), str):
        raise ValueError("Operational scope requires current task context")
    snapshot = context_snapshot(tables, root, receipt["task"])
    if receipt != context_receipt(snapshot, root):
        raise ValueError("Stale context; retrieve current task context before applying")
    if any(value is None for value in snapshot["sources"].values()):
        raise ValueError("Incomplete context: required source missing")
    scope_index = (
        {r["ID"]: r for rows in candidate.values() for r in rows}
        if candidate is not None
        else index
    )
    scopes = operational_nodules(index[receipt["task"]], scope_index)
    # Absorbed scope is retained provenance, not a competing active writer lane.
    if {key for key in governed - scopes if scope_index[key]["Status"] == "ACTIVE"}:
        raise ValueError("Context belongs to a different operational scope")
    for target in targets & index.keys():
        if target not in snapshot["rows"] and operational_nodules(index[target], index):
            raise ValueError(f"Target outside task context: {target}")
