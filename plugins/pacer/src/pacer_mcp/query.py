"""Bounded, row-addressed retrieval; never emit whole registers by default."""

from __future__ import annotations

from collections import Counter

from pacer_mcp.schema import HEADERS, PREFIX, REF_PATTERN, hard_blockers

DEFAULT_FIELDS = {
    "todo": ["ID", "Title", "Status", "Priority", "Assignee", "BlockedBy", "DoD"],
    "overlord": ["ID", "AssetType", "Path", "Symbol", "Purpose", "Requires", "RequiredBy"],
    "organism": ["ID", "Title", "Status", "Requirement", "BlockedByOGM", "PACRefs"],
    "nodule": ["ID", "NoduleName", "Status", "Lane", "Intent", "SpawnedPACs"],
}


def query_rows(
    tables: dict,
    register: str,
    *,
    where: dict | None = None,
    fields: list[str] | None = None,
    tag: str = "",
    ready: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """Filter exact values, shared tags and hard-gated readiness before pagination."""
    if register not in HEADERS:
        raise ValueError(f"Unknown register: {register}")
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("Query needs limit 1..100 and offset >= 0")
    if ready and register != "todo":
        raise ValueError("ready is a todo query")
    rows = tables[register]
    available = set(HEADERS[register]) | {k for row in rows for k in row}
    where = where or {}
    fields = DEFAULT_FIELDS[register] if fields is None else fields
    if not fields or (set(fields) | set(where)) - available:
        raise ValueError("Query contains unknown or empty projection columns")
    index = {row["ID"]: row for row in tables["todo"]}
    matches = []
    for row in rows:
        if any(row.get(k, "") != v for k, v in where.items()):
            continue
        if (
            tag
            and tag
            not in (row.get("Tags", "") + " " + row.get("RelatedWork", ""))
            .replace(";", " ")
            .split()
        ):
            continue
        if ready and (
            row["Status"] != "TODO"
            or any(index.get(r, {}).get("Status") != "DONE" for r in hard_blockers(row))
        ):
            continue
        matches.append(row)
    selected = matches[offset : offset + limit]
    return {
        "rows": [{k: row.get(k, "") for k in fields} for row in selected],
        "total": len(matches),
        "offset": offset,
        "next_offset": offset + limit if offset + limit < len(matches) else None,
    }


def health(tables: dict) -> dict:
    """Summarize real statuses without manufacturing progress percentages."""
    return {
        name: dict(Counter(r.get("Status", "") for r in tables[name]))
        for name in ("todo", "organism", "nodule")
    }


def graph(tables: dict, row_id: str, *, depth: int = 1, limit: int = 30) -> dict:
    """Follow a bounded cross-register reference neighborhood, including incoming refs."""
    if not 0 <= depth <= 3 or not 1 <= limit <= 100:
        raise ValueError("Graph needs depth 0..3 and limit 1..100")
    index = {r["ID"]: r for rows in tables.values() for r in rows}
    if row_id not in index:
        raise ValueError(f"REFUSAL: Unknown ID {row_id}")
    adjacency = {key: set() for key in index}
    for key, row in index.items():
        for value in row.values():
            for target in REF_PATTERN.findall(value):
                if target in index and target != key:
                    adjacency[key].add(target)
                    adjacency[target].add(key)
    visited = {row_id}
    frontier = [row_id]
    truncated = False
    for _ in range(depth):
        following = []
        for key in frontier:
            for target in sorted(adjacency[key]):
                if target in visited:
                    continue
                if len(visited) >= limit:
                    truncated = True
                    continue
                visited.add(target)
                following.append(target)
        frontier = following
    return {
        "ids": sorted(visited),
        "edges": [[a, b] for a in sorted(visited) for b in sorted(adjacency[a] & visited) if a < b],
        "truncated": truncated,
    }


def next_ids(tables: dict) -> dict:
    """Suggest unused base IDs; the revision precondition reserves them at apply time."""
    result = {}
    for register, prefix in PREFIX.items():
        numbers = [
            int(r["ID"].split("-")[1].rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
            for r in tables[register]
        ]
        result[register] = f"{prefix}-{max([0, *numbers]) + 1:03d}"
    return result
