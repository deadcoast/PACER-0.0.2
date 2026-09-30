"""Validate the complete candidate web before any publication."""

from __future__ import annotations

import re
from pathlib import Path

from pacer_mcp.schema import (
    AUTHORITIES,
    DEC_KINDS,
    HEADERS,
    ID_PATTERN,
    LIMITS,
    NDL_STATUSES,
    NEXT_ACTIONS,
    OGM_STATUSES,
    OVR_KINDS,
    PATH_FIELDS,
    PREFIX,
    REF_FIELDS,
    REGISTERS,
    TAG_PATTERN,
    TASK_KINDS,
    TASK_STATUSES,
    TIERS,
    contained_path,
    pos_parts,
    refs,
)

EVIDENCE_PATTERN = re.compile(
    r"rev:(?:[0-9a-f]{7}|none) src:[0-9a-f]{7} exit:-?\d+ out:[0-9a-f]{7} "
    r"at:\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"
)
POS_DEPTH = {"AREA": 1, "PHASE": 2, "PACE": 3}


def validate_web(tables: dict, root: Path, headers: dict | None = None) -> dict:
    """Report structural failures; warnings never block publication."""
    errors: list[str] = []
    warnings: list[str] = []
    index: dict[str, dict] = {}
    registers: dict[str, str] = {}
    if headers is not None:
        for register in REGISTERS:
            missing = set(HEADERS[register]) - set(headers.get(register, []))
            if missing:
                errors.append(f"{register}: missing columns {','.join(sorted(missing))}")
    for register in REGISTERS:
        for row in tables.get(register, []):
            row_id = row.get("ID", "")
            if row_id in index:
                errors.append(f"Duplicate ID {row_id}")
            if not ID_PATTERN.fullmatch(row_id) or not row_id.startswith(PREFIX[register] + "-"):
                errors.append(f"Invalid {register} ID {row_id}")
            index[row_id] = row
            registers[row_id] = register
            missing = set(HEADERS[register]) - row.keys()
            if missing:
                errors.append(f"{row_id}: missing columns {','.join(sorted(missing))}")
    for row_id, row in index.items():
        register = registers[row_id]
        for field, value in row.items():
            if not isinstance(value, str):
                errors.append(f"{row_id}.{field}: string required")
                continue
            if "|" in value or "\n" in value or "\r" in value:
                errors.append(f"{row_id}.{field}: contains | or newline")
            if field in LIMITS and len(value) > LIMITS[field]:
                errors.append(f"{row_id}: {field} exceeds {LIMITS[field]}")
        for field, prefix in REF_FIELDS[register].items():
            values = refs(row.get(field, ""))
            if len(values) != len(set(values)):
                errors.append(f"{row_id}.{field}: duplicate reference")
            for target in values:
                ok = ID_PATTERN.fullmatch(target) and (
                    prefix == "*" or target.startswith(prefix + "-")
                )
                if not ok:
                    errors.append(f"{row_id}.{field}: invalid reference {target}")
                elif target not in index:
                    errors.append(f"REFUSAL: Unknown ID {target}")
        for field in PATH_FIELDS.get(register, ()):
            items = [row.get("Path", "")] if field == "Path" else refs(row.get(field, ""))
            for item in items:
                try:
                    contained_path(root, item.split(":", 1)[0])
                except ValueError as exc:
                    errors.append(f"{row_id}: {exc}")
        if any(not TAG_PATTERN.fullmatch(t) for t in row.get("Tags", "").split()):
            errors.append(f"{row_id}: invalid Tags")
        if row.get("Tier") and row["Tier"] not in TIERS:
            errors.append(f"{row_id}: invalid Tier")
        if register == "todo":
            _todo(row, row_id, index, errors, warnings)
        elif register == "overlord":
            _overlord(row, row_id, tables, root, errors, warnings)
        elif register == "organism":
            _organism(row, row_id, errors)
        elif register == "nodule":
            _nodule(row, row_id, errors)
        else:
            _decision(row, row_id, errors)
    edges = {
        r["ID"]: [t for t in refs(r.get("Needs", "")) if registers.get(t) == "todo"]
        for r in tables["todo"]
    }
    if _has_cycle(edges):
        errors.append("REFUSAL: Circular dependency detected")
    active = [r for r in tables["nodule"] if r.get("Status") == "ACTIVE"]
    for i, row in enumerate(active):
        for other in active[i + 1 :]:
            same_lane = row.get("Lane") == other.get("Lane")
            overlap = set(refs(row.get("In", ""))) & set(refs(other.get("In", "")))
            if same_lane or overlap:
                errors.append("REFUSAL: Nodule lane occupied")
    return {"valid": not errors, "errors": list(dict.fromkeys(errors)), "warnings": warnings}


def effective_task_tier(row: dict, index: dict, default: str = "prototype") -> str:
    """A PACE inherits its PHASE tier; an explicit tier only raises it."""
    own = row.get("Tier") or ""
    parent = ""
    try:
        area, phase, pace = pos_parts(row.get("Pos", ""))
    except ValueError:
        return own or default
    if pace is not None:
        for other in index.values():
            if other.get("Kind") == "PHASE" and other.get("Pos") == f"A{area}.P{phase}":
                parent = other.get("Tier") or ""
    candidates = [t for t in (own, parent, default) if t in TIERS]
    return max(candidates, key=TIERS.index) if candidates else default


def _todo(row, row_id, index, errors, warnings):
    kind, status = row.get("Kind"), row.get("Status")
    if kind not in TASK_KINDS:
        errors.append(f"{row_id}: invalid Kind")
    if status not in TASK_STATUSES:
        errors.append(f"{row_id}: invalid task status")
    if not row.get("Title"):
        errors.append(f"{row_id}: Title required")
    try:
        parts = pos_parts(row.get("Pos", ""))
        depth = sum(p is not None for p in parts)
        if kind in POS_DEPTH and depth != POS_DEPTH[kind]:
            errors.append(f"{row_id}: Pos depth does not match Kind {kind}")
    except ValueError as exc:
        errors.append(f"{row_id}: {exc}")
    if kind == "PHASE" and not row.get("Exit"):
        errors.append(f"{row_id}: PHASE requires Exit")
    if kind == "PACE" and not row.get("Produce"):
        errors.append(f"{row_id}: PACE requires Produce")
    if row.get("Next") and row["Next"] not in NEXT_ACTIONS:
        errors.append(f"{row_id}: invalid Next")
    tier = effective_task_tier(row, index)
    if kind == "PACE" and TIERS.index(tier) >= TIERS.index("integrated") and not row.get("Probe"):
        warnings.append(f"{row_id}: Probe required at tier {tier}")
    blocked = [t for t in refs(row.get("Needs", "")) if index.get(t, {}).get("Status") != "DONE"]
    if status == "DONE" and blocked:
        errors.append(f"REFUSAL: Blocked by {';'.join(blocked)}")


def _overlord(row, row_id, tables, root, errors, warnings):
    if row.get("Kind") not in OVR_KINDS:
        errors.append(f"{row_id}: invalid Kind")
    try:
        path = contained_path(root, row.get("Path", ""))
        if not path.is_file() and "#dead" not in row.get("Tags", "").split():
            errors.append(f"{row_id}: path does not exist: {row.get('Path')}")
    except ValueError as exc:
        errors.append(f"{row_id}: {exc}")
    if row.get("Kind") != "FILE" and not any(
        r.get("Path") == row.get("Path") and r.get("Kind") == "FILE" for r in tables["overlord"]
    ):
        errors.append(f"{row_id}: FILE row required for {row.get('Path')}")
    if not row.get("Purpose"):
        warnings.append(f"{row_id}: #unpurposed")


def _organism(row, row_id, errors):
    if row.get("Status") not in OGM_STATUSES:
        errors.append(f"{row_id}: invalid organism status")
    if row.get("Authority") and row["Authority"] not in AUTHORITIES:
        errors.append(f"{row_id}: invalid Authority")
    if not row.get("Requirement"):
        errors.append(f"{row_id}: Requirement required")
    evidence = row.get("Evidence", "")
    if evidence and not EVIDENCE_PATTERN.fullmatch(evidence):
        errors.append(f"{row_id}: invalid Evidence cell")
    if row.get("Status") == "VALIDATED_COMPLETE" and not (evidence and " exit:0 " in evidence):
        errors.append("REFUSAL: Evidence required")


def _nodule(row, row_id, errors):
    if row.get("Status") not in NDL_STATUSES:
        errors.append(f"{row_id}: invalid nodule status")
    for field in ("Name", "Lane", "Request", "Intent", "Exit"):
        if not row.get(field):
            errors.append(f"{row_id}: {field} required")
    if row.get("Status") == "ACTIVE" and not row.get("Spawned"):
        errors.append(f"{row_id}: ACTIVE nodule requires Spawned")


def _decision(row, row_id, errors):
    if row.get("Kind") not in DEC_KINDS:
        errors.append(f"{row_id}: invalid Kind")
    if row.get("Latched", "") not in {"", "true", "false"}:
        errors.append(f"{row_id}: Latched must be true or false")
    if (
        row.get("Kind") == "LATCH"
        and row.get("Latched") == "true"
        and row.get("Authority") != "USER"
    ):
        errors.append(f"{row_id}: LATCH requires Authority USER")
    if row.get("Authority") and row["Authority"] not in AUTHORITIES:
        errors.append(f"{row_id}: invalid Authority")
    if not row.get("Subject"):
        errors.append(f"{row_id}: Subject required")


def _has_cycle(edges: dict[str, list[str]]) -> bool:
    indegree = dict.fromkeys(edges, 0)
    for targets in edges.values():
        for target in targets:
            if target in indegree:
                indegree[target] += 1
    ready = [k for k, c in indegree.items() if c == 0]
    seen = 0
    while ready:
        key = ready.pop()
        seen += 1
        for target in edges[key]:
            if target in indegree:
                indegree[target] -= 1
                if indegree[target] == 0:
                    ready.append(target)
    return seen != len(edges)
