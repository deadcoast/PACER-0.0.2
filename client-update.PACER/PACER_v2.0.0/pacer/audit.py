from __future__ import annotations
from .model import Plan

def audit(plan: Plan) -> list[str]:
    warnings: list[str] = []
    phases = [p for g in plan.globals for p in g.phases]
    paces = [x for p in phases for x in p.paces]
    user_gates = [(p, gate) for p in phases for gate in p.gates if gate[0].lower() == "user"]

    if not plan.has_loop:
        warnings.append("CONTINUITY: no :loop⠁: marker found; plan can park after a local pace.")

    single = [p.id for p in phases if len(p.paces) == 1]
    if len(single) >= 3:
        warnings.append(f"FRAGMENTATION: {len(single)} one-pace phases ({', '.join(single[:6])}); group related work into integrated phases.")

    reviewish = []
    for g in plan.globals:
        if g.state.lower() == "review": reviewish.append(g.id)
        for p in g.phases:
            if p.state.lower() == "review": reviewish.append(p.id)
            reviewish.extend(x.id for x in p.paces if x.state.lower() == "review")
    if reviewish:
        warnings.append(f"REVIEW_PARKING: REVIEW used as lifecycle state for {len(reviewish)} item(s); v2 treats review as evidence, not a mandatory stop.")

    if paces and len(user_gates) / len(paces) > 0.20:
        warnings.append(f"GATE_DENSITY: {len(user_gates)} user gates across {len(paces)} paces; user intervention should be exceptional.")

    for phase, (kind, reason) in user_gates:
        if len(phase.paces) <= 1:
            warnings.append(f"MICRO_GATE: {phase.id} asks user after {len(phase.paces)} pace(s): {reason or 'unspecified reason'}")

    for p in phases:
        if not p.exit:
            warnings.append(f"COHERENCE: {p.id} has no phase EXIT condition; agent lacks an integrated stopping point.")

    if not warnings:
        warnings.append("OK: no continuity anti-patterns detected by the advisory audit.")
    return warnings
