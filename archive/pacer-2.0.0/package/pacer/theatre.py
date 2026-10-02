from __future__ import annotations
from .model import Plan, Phase

def select_phase(plan: Plan, phase_id: str | None = None) -> tuple[object, Phase] | tuple[None, None]:
    for g in plan.globals:
        for p in g.phases:
            if phase_id and p.id == phase_id:
                return g, p
    if phase_id:
        return None, None
    for g in plan.globals:
        for p in g.phases:
            if p.state.lower() == "active":
                return g, p
    for g in plan.globals:
        for p in g.phases:
            if p.state.lower() not in {"done", "integrated"}:
                return g, p
    if plan.globals and plan.globals[-1].phases:
        return plan.globals[-1], plan.globals[-1].phases[-1]
    return None, None

def compile_theatre(plan: Plan, phase_id: str | None = None) -> str:
    g, p = select_phase(plan, phase_id)
    if not p:
        return "No eligible phase."
    lines = [
        f"PACER THEATRE :: {plan.project}",
        f"MATURITY      {plan.maturity}",
        f"GLOBAL        {g.id}  {g.title}",
        f"PHASE         {p.id}  {p.title}",
        "",
        "ACTIONABLE PACES",
    ]
    for pace in p.paces:
        lines.append(f"  {pace.id:<10} {pace.state:<10} {pace.title}")
    sources = list(dict.fromkeys([*g.sources, *p.sources]))
    if sources:
        lines += ["", "SOURCE ANCHORS"] + [f"  - {s}" for s in sources]
    if p.exit:
        lines += ["", f"EXIT          {p.exit}"]
    lines += ["", "CONTINUE      integrate → self-check → absorb → :loop⠁: → OVERLORD update"]
    return "\n".join(lines)
