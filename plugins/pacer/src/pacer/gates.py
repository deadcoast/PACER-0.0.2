"""The tier matrix: when a stop is blocked and when an edit is denied.

    tier                         stop blocks when                 edit denied when
    sketch, prototype, playable  never                            never
    integrated                   a bound probe FAILED             never
    release                      a bound probe FAILED or STALE    never
    protected                    as release                       no USER latch covers the path

An open LATCH on the active work blocks a stop at every tier: it is the one
question only the user can answer.
"""

from __future__ import annotations

from pacer import schema
from pacer.frames import Compiler, active_pace, bound_requirements, phase_of
from pacer.probe import freshness
from pacer.schema import TIERS, refs

AT_LEAST = {tier: rank for rank, tier in enumerate(TIERS)}


def effective_tier(row: dict | None, tables: dict, config: dict) -> str:
    """A PACE inherits its PHASE tier; explicit tiers only raise; the project tier is the floor."""
    phase = phase_of(row, tables) if row and row.get("Kind") == "PACE" else None
    return schema.effective_tier(row, phase, config["tier"])


def open_latches(subjects: set[str], tables: dict) -> list[str]:
    return sorted(
        r["ID"]
        for r in tables["decision"]
        if r.get("Kind") == "LATCH"
        and r.get("Latched") == "false"
        and set(refs(r.get("Subject", ""))) & subjects
    )


def stop_decision(compiler: Compiler) -> dict:
    """Block only per the matrix; always compute the durable next action."""
    tables, store = compiler.tables, compiler.store
    pace = active_pace(tables, store)
    phase = phase_of(pace, tables)
    tier = effective_tier(pace, tables, compiler.config)
    requirements = {r["ID"]: r for r in tables["organism"]}
    states = {
        key: freshness(requirements[key], tables, compiler.root)
        for key in bound_requirements(phase, pace)
        if key in requirements
    }
    failed = [k for k, s in states.items() if s == "FAIL"]
    stale = [k for k, s in states.items() if s == "STALE"]
    reasons: list[str] = []
    if AT_LEAST[tier] >= AT_LEAST["integrated"] and failed:
        reasons.append("probe failed: " + ", ".join(failed))
    if AT_LEAST[tier] >= AT_LEAST["release"] and stale:
        reasons.append("evidence stale: " + ", ".join(stale))
    subjects = {r["ID"] for r in (pace, phase) if r} | set(states)
    if pace:
        subjects |= set(refs(pace.get("In", "")))
    latches = open_latches(subjects, tables)
    if latches:
        reasons.append("open latch: " + ", ".join(latches))
    worked = pace is not None and any(
        e.get("op") == "touch" for e in store.ledger_read(pace["ID"], 50)
    )
    if latches:
        next_action = "inspect"
    elif failed or stale:
        next_action = "verify"
    elif worked:
        next_action = "integrate"
    else:
        next_action = (pace or {}).get("Next") or "implement"
    lines = [f"PACER stop tier={tier} pace={pace['ID'] if pace else 'none'} next={next_action}"]
    lines += [compiler.render(key) for key in latches]
    lines += [f"{key}: {state}" for key, state in states.items() if state != "CURRENT"]
    return {
        "block": bool(reasons),
        "reasons": reasons,
        "open_latches": latches,
        "next": next_action,
        "text": "\n".join(lines),
    }


def edit_decision(compiler: Compiler, path: str) -> dict:
    """Deny only at protected tier, and only when no USER latch covers the asset or the pace."""
    tables = compiler.tables
    assets = [r for r in tables["overlord"] if r.get("Path") == path]
    pace = active_pace(tables, compiler.store)
    tiers = [r["Tier"] for r in assets if r.get("Tier") in AT_LEAST]
    tiers.append(effective_tier(pace, tables, compiler.config))
    if max(tiers, key=AT_LEAST.__getitem__) != "protected":
        return {"deny": False, "reason": ""}
    subjects = {r["ID"] for r in assets} | ({pace["ID"]} if pace else set())
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
        "reason": f"{path} is protected: a USER latch (DEC LATCH) covering it is required",
    }
