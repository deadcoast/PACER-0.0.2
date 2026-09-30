"""Indented plan view; a rendering of todo.PACER.csv, never a store."""

from __future__ import annotations

from pacer_mcp.schema import VERSION, pos_parts


def _key(row: dict):
    try:
        area, phase, pace = pos_parts(row.get("Pos", ""))
    except ValueError:
        return (10**6, 0, 0)
    return (area, phase or 0, pace or 0)


def render_tree(tables: dict, spec: dict) -> str:
    rows = sorted((r for r in tables["todo"] if r.get("Pos")), key=_key)
    lines = [f"PACER::TODO version={VERSION} project={spec['project']} tier={spec['tier']}"]
    for r in rows:
        kind = r["Kind"]
        if kind == "AREA":
            lines.append(f'AREA {r["ID"]} {r["Pos"]} "{r["Title"]}" {r["Status"]}')
        elif kind == "PHASE":
            tier = f" {r['Tier']}" if r.get("Tier") else ""
            lines.append(
                f'  PHASE {r["ID"]} {r["Pos"]} "{r["Title"]}" {r["Status"]}{tier} '
                f'exit="{r["Exit"]}"'
            )
        else:
            pairs = (("in", "In"), ("out", "Out"), ("binds", "Binds"), ("needs", "Needs"))
            extra = "".join(f" {k}={r[c]}" for k, c in pairs if r.get(c))
            lines.append(f'    PACE {r["ID"]} {r["Pos"]} {r["Status"]} "{r["Produce"]}"{extra}')
    return "\n".join(lines)
