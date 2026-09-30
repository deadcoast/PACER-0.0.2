"""Compile bounded card frames for harness events. Never refuse on budget."""

from __future__ import annotations

import re
from pathlib import Path

from pacer_mcp.cards import card
from pacer_mcp.probe import bound_paths, freshness, parse_evidence
from pacer_mcp.rank import rank
from pacer_mcp.schema import REF_PATTERN, REGISTERS, TAG_PATTERN, pos_parts, refs

PATH_TOKEN = re.compile(r"(?<![\w./-])((?:[\w.-]+/)*[\w-]+\.[A-Za-z0-9]+)")
MAX_USED_BY = 8


def _index(tables: dict) -> dict[str, tuple[str, dict]]:
    return {r["ID"]: (reg, r) for reg in REGISTERS for r in tables.get(reg, [])}


def _sort_key(row: dict):
    try:
        area, phase, pace = pos_parts(row.get("Pos", ""))
    except ValueError:
        return (10**6, 0, 0)
    return (area, phase or 0, pace or 0)


def phase_of(row: dict | None, tables: dict) -> dict | None:
    """The PHASE row governing a PACE; a PHASE governs itself."""
    if row is None:
        return None
    try:
        area, phase, pace = pos_parts(row.get("Pos", ""))
    except ValueError:
        return None
    if pace is None:
        return row if phase is not None else None
    for other in tables["todo"]:
        if other.get("Kind") == "PHASE" and other.get("Pos") == f"A{area}.P{phase}":
            return other
    return None


def active_pace(tables: dict, store) -> dict | None:
    """The single ACTIVE pace, else the most recently touched one, else the lowest position."""
    active = [r for r in tables["todo"] if r.get("Kind") == "PACE" and r.get("Status") == "ACTIVE"]
    if not active:
        return None
    if len(active) == 1:
        return active[0]
    ids = {r["ID"]: r for r in active}
    for entry in reversed(store.ledger_read(None, 200)):
        if entry.get("op") in {"touch", "status", "checkpoint"} and entry.get("id") in ids:
            return ids[entry["id"]]
    return sorted(active, key=_sort_key)[0]


def ogm_extras(row: dict, tables: dict, root: Path) -> dict:
    state = freshness(row, tables, root)
    parsed = parse_evidence(row.get("Evidence", ""))
    if parsed is None:
        return {"Evidence": "UNBOUND"}
    text = f"rev:{parsed['rev']} exit:{parsed['exit']} at:{parsed['at'][:10]}"
    if state == "STALE":
        text += " STALE(" + ",".join(bound_paths(row, tables)[:3]) + ")"
    else:
        text += f" {state}"
    return {"Evidence": text}


def ovr_extras(row: dict, provider) -> dict:
    if row.get("Kind") != "FILE":
        return {}
    users = sorted(provider.users(row["Path"]))
    if not users:
        return {}
    shown = ", ".join(users[:MAX_USED_BY])
    if len(users) > MAX_USED_BY:
        shown += f" (+{len(users) - MAX_USED_BY})"
    return {"used-by": shown}


def render(key: str, tables: dict, root: Path, provider, extra: dict | None = None) -> str:
    """One card with computed extras (freshness, dependents)."""
    register, row = _index(tables)[key]
    extras = dict(extra or {})
    if register == "organism":
        extras.update(ogm_extras(row, tables, root))
    elif register == "overlord":
        extras.update(ovr_extras(row, provider))
    return card(register, row, extras)


def fit(lines: list[str], spine: list[str], budget: int, focus: str) -> str:
    """Spine always; then lines in order until the budget; trailer reports the rest."""
    out = list(spine)
    used = sum(len(line.encode("utf-8")) + 1 for line in out)
    dropped = 0
    for line in lines:
        if line in out:
            continue
        size = len(line.encode("utf-8")) + 1
        if used + size > budget:
            dropped += 1
            continue
        out.append(line)
        used += size
    if dropped:
        out.append(f"+{dropped} more: pacer q {focus}")
    return "\n".join(out)


def _head(spec: dict, pace: dict | None) -> str:
    return f"PACER {spec['project']} tier={spec['tier']} pace={pace['ID'] if pace else 'none'}"


def _bound_ogms(phase: dict | None, pace: dict | None, tables: dict) -> list[str]:
    keys: list[str] = []
    for row in (phase, pace):
        if row:
            keys += refs(row.get("Binds", ""))
    return list(dict.fromkeys(keys))


def _decisions_for(subjects: set[str], tables: dict) -> list[str]:
    superseded = {r["Supersedes"] for r in tables["decision"] if r.get("Supersedes")}
    return [
        r["ID"]
        for r in tables["decision"]
        if set(refs(r.get("Subject", ""))) & subjects and r["ID"] not in superseded
    ]


def session_frame(tables: dict, root: Path, store, provider, spec: dict) -> str:
    pace = active_pace(tables, store)
    phase = (
        phase_of(pace, tables)
        if pace
        else next(
            (r for r in tables["todo"] if r.get("Kind") == "PHASE" and r.get("Status") == "ACTIVE"),
            None,
        )
    )
    area = None
    if phase:
        a, _, _ = pos_parts(phase["Pos"])
        area = next(
            (r for r in tables["todo"] if r.get("Kind") == "AREA" and r.get("Pos") == f"A{a}"),
            None,
        )
    spine_ids = [r["ID"] for r in (area, phase, pace) if r]
    subjects = set(spine_ids) | (set(refs(pace.get("In", ""))) if pace else set())
    ogms = _bound_ogms(phase, pace, tables)
    subjects |= set(ogms)
    spine_ids += _decisions_for(subjects, tables)
    spine_ids = list(dict.fromkeys(spine_ids))
    spine = [_head(spec, pace)] + [render(k, tables, root, provider) for k in spine_ids]
    focus = [pace["ID"]] if pace else ([phase["ID"]] if phase else [])
    if focus:
        ranked = [k for _, k in rank(tables, provider, focus)]
    else:
        ranked = [
            r["ID"] for r in sorted(tables["todo"], key=_sort_key) if r.get("Status") == "TODO"
        ][:5]
        spine.append("no active pace; start one: pacer status <PAC> ACTIVE")
    next_paces = [
        r["ID"]
        for r in sorted(tables["todo"], key=_sort_key)
        if r.get("Kind") == "PACE"
        and r.get("Status") == "TODO"
        and phase is not None
        and phase_of(r, tables) is phase
    ][:5]
    ordered = list(dict.fromkeys(ogms + next_paces + ranked))
    lines = [render(k, tables, root, provider) for k in ordered if k not in spine_ids]
    return fit(lines, spine, spec["budgets"]["session"], focus[0] if focus else "todo")


def edit_frame(tables: dict, root: Path, store, provider, spec: dict, path: str) -> str:
    pace = active_pace(tables, store)
    rows = [r for r in tables["overlord"] if r.get("Path") == path]
    in_pace = False
    if pace:
        in_ids = set(refs(pace.get("In", "")))
        outs = [o.split(":", 1)[0] for o in refs(pace.get("Out", ""))]
        in_pace = any(r["ID"] in in_ids for r in rows) or path in outs
    spine = [_head(spec, pace)]
    lines: list[str] = []
    subjects: set[str] = set()
    if not rows:
        users = provider.users(path)
        extra = f" | used-by: {', '.join(users[:MAX_USED_BY])}" if users else ""
        spine.append(f"OVR - {path} unregistered{extra}")
    else:
        for row in rows:
            extra = {} if in_pace or not pace else {"OFF-PACE": "1"}
            spine.append(render(row["ID"], tables, root, provider, extra))
        subjects = {r["ID"] for r in rows}
    ogms = [r["ID"] for r in tables["organism"] if set(refs(r.get("Binds", ""))) & subjects]
    decs = _decisions_for(subjects, tables)
    for key in ogms + decs:
        spine.append(render(key, tables, root, provider))
    if pace:
        lines.append(render(pace["ID"], tables, root, provider))
    ranked = [k for _, k in rank(tables, provider, sorted(subjects))] if subjects else []
    skip = subjects | set(ogms) | set(decs)
    lines += [render(k, tables, root, provider) for k in ranked if k not in skip]
    return fit(lines, spine, spec["budgets"]["edit"], next(iter(sorted(subjects)), path))


def prompt_frame(tables: dict, root: Path, provider, spec: dict, prompt: str) -> str:
    index = _index(tables)
    ids = [i for i in REF_PATTERN.findall(prompt) if i in index]
    mentioned = set(PATH_TOKEN.findall(prompt))
    paths = sorted(r["ID"] for r in tables["overlord"] if r.get("Path") in mentioned)
    tags = set(TAG_PATTERN.findall(prompt))
    tagged = [
        r["ID"] for reg in REGISTERS for r in tables[reg] if tags & set(r.get("Tags", "").split())
    ]
    keys = list(dict.fromkeys(ids + paths + tagged))
    if not keys:
        return ""
    lines = [render(k, tables, root, provider) for k in keys]
    return fit(lines, [], spec["budgets"]["prompt"], keys[0])
