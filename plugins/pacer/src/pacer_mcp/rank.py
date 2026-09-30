"""Relevance by weighted distance over typed edges, tree position and derived structure."""

from __future__ import annotations

import heapq

from pacer_mcp.schema import REF_FIELDS, REGISTERS, pos_parts, refs

W_REF, W_TREE, W_NEEDS, W_FILE, W_AREA = 1, 1, 2, 2, 3


def adjacency(tables: dict, provider) -> dict[str, dict[str, int]]:
    """Undirected weighted graph over every row ID."""
    graph: dict[str, dict[str, int]] = {}

    def edge(a: str, b: str, w: int):
        if a == b:
            return
        graph.setdefault(a, {})
        graph.setdefault(b, {})
        graph[a][b] = min(graph[a].get(b, w), w)
        graph[b][a] = min(graph[b].get(a, w), w)

    index = {r["ID"]: r for reg in REGISTERS for r in tables.get(reg, [])}
    for key in index:
        graph.setdefault(key, {})
    for register in REGISTERS:
        for row in tables.get(register, []):
            for field in REF_FIELDS[register]:
                weight = W_NEEDS if field == "Needs" else W_REF
                for target in refs(row.get(field, "")):
                    if target in index:
                        edge(row["ID"], target, weight)
    by_pos: dict[str, str] = {}
    for row in tables.get("todo", []):
        try:
            pos_parts(row.get("Pos", ""))
        except ValueError:
            continue
        by_pos[row["Pos"]] = row["ID"]
    parsed = {pos: pos_parts(pos) for pos in by_pos}
    for pos, key in by_pos.items():
        area, phase, pace = parsed[pos]
        if pace is not None:
            parent = f"A{area}.P{phase}"
        elif phase is not None:
            parent = f"A{area}"
        else:
            parent = None
        if parent in by_pos:
            edge(key, by_pos[parent], W_TREE)
        for other_pos, other in by_pos.items():
            if other == key:
                continue
            oa, op, opace = parsed[other_pos]
            if oa != area:
                continue
            if op == phase and pace is not None and opace is not None:
                edge(key, other, W_TREE)
            elif phase is not None and op is not None and phase != op:
                edge(key, other, W_AREA)
    files = {r["Path"]: r["ID"] for r in tables.get("overlord", []) if r.get("Kind") == "FILE"}
    for path, key in files.items():
        for other in provider.users(path) + provider.deps(path):
            if other in files:
                edge(key, files[other], W_FILE)
    return graph


def rank(tables: dict, provider, focus: list[str]) -> list[tuple[int, str]]:
    """Dijkstra from the focus set; returns (distance, ID) ascending."""
    graph = adjacency(tables, provider)
    dist = {key: 0 for key in focus if key in graph}
    heap = [(0, key) for key in dist]
    while heap:
        d, key = heapq.heappop(heap)
        if d > dist.get(key, 10**9):
            continue
        for other, w in graph.get(key, {}).items():
            nd = d + w
            if nd < dist.get(other, 10**9):
                dist[other] = nd
                heapq.heappush(heap, (nd, other))
    return sorted((d, k) for k, d in dist.items())
