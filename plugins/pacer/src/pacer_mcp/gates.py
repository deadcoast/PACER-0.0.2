"""Tier matrix: the whole guardrail doctrine as a lookup."""

from __future__ import annotations

from pathlib import Path

from pacer_mcp.frames import _bound_ogms, active_pace, phase_of, render
from pacer_mcp.probe import freshness
from pacer_mcp.schema import TIERS, refs

AT_LEAST = {t: i for i, t in enumerate(TIERS)}


def effective_tier(row: dict | None, tables: dict, spec: dict) -> str:
    """A PACE inherits its PHASE tier; explicit tiers only raise; the spec is the floor."""
    if row is None:
        return spec["tier"]
    own = row.get("Tier") or ""
    parent = ""
    if row.get("Kind") == "PACE":
        phase = phase_of(row, tables)
        parent = (phase or {}).get("Tier") or ""
    candidates = [t for t in (own, parent, spec["tier"]) if t in AT_LEAST]
    return max(candidates, key=lambda t: AT_LEAST[t]) if candidates else spec["tier"]


def open_latches(subjects: set[str], tables: dict) -> list[str]:
    return sorted(
        r["ID"]
        for r in tables["decision"]
        if r.get("Kind") == "LATCH"
        and r.get("Latched") == "false"
        and set(refs(r.get("Subject", ""))) & subjects
    )


def stop_decision(tables: dict, root: Path, store, provider, spec: dict) -> dict:
    """Block only per the matrix; always compute the durable next action."""
    pace = active_pace(tables, store)
    phase = phase_of(pace, tables) if pace else None
    tier = effective_tier(pace, tables, spec)
    index = {r["ID"]: r for r in tables["organism"]}
    reasons: list[str] = []
    states = {}
    for key in _bound_ogms(phase, pace, tables):
        if key in index:
            states[key] = freshness(index[key], tables, root)
    fails = [k for k, s in states.items() if s == "FAIL"]
    stale = [k for k, s in states.items() if s == "STALE"]
    if AT_LEAST[tier] >= AT_LEAST["integrated"] and fails:
        reasons.append("probe failed: " + ", ".join(f"{k} FAIL" for k in fails))
    if AT_LEAST[tier] >= AT_LEAST["release"] and stale:
        reasons.append("evidence stale: " + ", ".join(stale))
    subjects = {r["ID"] for r in (pace, phase) if r} | set(states)
    if pace:
        subjects |= set(refs(pace.get("In", "")))
    latches = open_latches(subjects, tables)
    if latches:
        reasons.append("open latch: " + ", ".join(latches))
    touched = (
        [e for e in store.ledger_read(pace["ID"], 50) if e.get("op") == "touch"] if pace else []
    )
    if latches:
        next_action = "inspect"
    elif fails or stale:
        next_action = "verify"
    elif touched:
        next_action = "integrate"
    else:
        next_action = (pace or {}).get("Next") or "implement"
    lines = [f"PACER stop tier={tier} pace={pace['ID'] if pace else 'none'} next={next_action}"]
    lines += [render(k, tables, root, provider) for k in latches]
    lines += [f"{k}: {s}" for k, s in states.items() if s != "CURRENT"]
    return {
        "block": bool(reasons),
        "reasons": reasons,
        "open_latches": latches,
        "next": next_action,
        "text": "\n".join(lines),
    }


def edit_decision(tables: dict, root: Path, store, spec: dict, path: str) -> dict:
    """Deny only at protected tier without a USER latch covering the asset or pace."""
    rows = [r for r in tables["overlord"] if r.get("Path") == path]
    pace = active_pace(tables, store)
    tiers = [r["Tier"] for r in rows if r.get("Tier") in AT_LEAST] or [
        effective_tier(pace, tables, spec)
    ]
    tier = max(tiers, key=lambda t: AT_LEAST[t])
    if tier != "protected":
        return {"deny": False, "reason": ""}
    subjects = {r["ID"] for r in rows} | ({pace["ID"]} if pace else set())
    covered = any(
        r.get("Kind") == "LATCH"
        and r.get("Latched") == "true"
        and r.get("Authority") == "USER"
        and set(refs(r.get("Subject", ""))) & subjects
        for r in tables["decision"]
    )
    if covered:
        return {"deny": False, "reason": ""}
    return {
        "deny": True,
        "reason": f"{path} is protected; a USER latch (DEC LATCH) covering it is required",
    }
