"""Validate the whole connected web before publishing any candidate change."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pacer_mcp.schema import (
    HEADERS,
    ID_PATTERN,
    OGM_STATUSES,
    PAIRS,
    PREFIX,
    REF_FIELDS,
    REF_PATTERN,
    TAG_PATTERN,
    contained_path,
    hard_blockers,
    refs,
)
from pacer_mcp.semantics import (
    APPROVAL_STATES,
    LITERAL_FIELDS,
    NEXT_ACTIONS,
    approval_allowed,
    approval_state,
    rule_errors,
)


def validate_web(
    tables: dict[str, list[dict[str, str]]], root: Path, headers: dict[str, list[str]] | None = None
) -> dict:
    """Report structural failures separately from actionable stale-work warnings."""
    errors: list[str] = []
    warnings: list[str] = []
    index = {}
    registers = {}
    if headers is not None:
        for register, required in HEADERS.items():
            missing = set(required) - set(headers.get(register, []))
            if missing:
                errors.append(f"{register}: missing columns {','.join(sorted(missing))}")
    for register, rows in tables.items():
        for row in rows:
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
            for reference in [] if field in LITERAL_FIELDS else REF_PATTERN.findall(value):
                if reference not in index:
                    errors.append(f"REFUSAL: Unknown ID {reference}")
        for field, prefix in REF_FIELDS[register].items():
            values = refs(row.get(field, ""))
            if len(values) != len(set(values)):
                errors.append(f"{row_id}.{field}: duplicate reference")
            for target in values:
                if not ID_PATTERN.fullmatch(target) or not target.startswith(prefix + "-"):
                    errors.append(f"{row_id}.{field}: invalid reference {target}")
        if any(not TAG_PATTERN.fullmatch(t) for t in row.get("Tags", "").split()):
            errors.append(f"{row_id}: invalid Tags")
        if "#template-example" in row.get("Tags", "").split():
            errors.append(f"{row_id}: worked example in live register")
        for field in ("StartedAt", "DoneAt", "UpdatedAt", "CreatedAt", "AbsorbedAt", "ApprovedAt"):
            if row.get(field):
                try:
                    timestamp = datetime.fromisoformat(row[field].replace("Z", "+00:00"))
                    if timestamp.utcoffset() != timedelta(0):
                        raise ValueError
                except ValueError:
                    errors.append(f"{row_id}.{field}: UTC ISO 8601 required")
        if register == "todo":
            if approval_state(row) not in APPROVAL_STATES:
                errors.append(f"{row_id}: invalid approval state")
            if approval_state(row) == "APPROVED" and not approval_allowed(row):
                errors.append(f"{row_id}: approval evidence or scope binding invalid")
            if row.get("Status") in {"DOING", "REVIEW", "DONE"} and not approval_allowed(row):
                errors.append(f"{row_id}: approval required for active or completed work")
            if row.get("NextAction") and row["NextAction"] not in NEXT_ACTIONS:
                errors.append(f"{row_id}: invalid NextAction")
            if row.get("Status") not in {"TODO", "DOING", "REVIEW", "DONE"}:
                errors.append(f"{row_id}: invalid task status")
            if not row.get("Title") or not row.get("DoD"):
                errors.append(f"{row_id}: Title and DoD required")
            try:
                blocked = [
                    r for r in hard_blockers(row) if index.get(r, {}).get("Status") != "DONE"
                ]
                if row.get("Status") == "DONE" and blocked:
                    errors.append(f"REFUSAL: Blocked by {';'.join(blocked)}")
            except ValueError as exc:
                errors.append(str(exc))
            if row.get("Status") in {"DOING", "REVIEW", "DONE"} and not row.get("StartedAt"):
                errors.append(f"{row_id}: StartedAt required")
            if row.get("Status") == "DOING":
                if not row.get("Assignee"):
                    errors.append(f"{row_id}: Assignee required while DOING")
                try:
                    start = datetime.fromisoformat(row["StartedAt"].replace("Z", "+00:00"))
                    if datetime.now(UTC) - start > timedelta(hours=48):
                        warnings.append(f"{row_id}: DOING exceeds 48h; split before advancing")
                except (ValueError, TypeError):
                    pass
            if row.get("Status") == "DONE" and not row.get("DoneAt"):
                errors.append(f"{row_id}: DoneAt required")
            if row.get("Status") != "DONE" and row.get("DoneAt"):
                errors.append(f"{row_id}: DoneAt requires DONE")
        elif register == "overlord":
            if row.get("AssetType") not in {
                "FILE",
                "MODULE",
                "CLASS",
                "FUNCTION",
                "METHOD",
                "CONFIG",
                "SCHEMA",
            }:
                errors.append(f"{row_id}: invalid AssetType")
            if not row.get("Purpose"):
                errors.append(f"{row_id}: Purpose required")
            try:
                path = contained_path(root, row.get("Path", ""))
                pending_register = row.get("Path") in {f"{n}.PACER.csv" for n in HEADERS}
                if (
                    not path.is_file()
                    and not pending_register
                    and "#dead" not in row.get("Tags", "").split()
                ):
                    errors.append(f"{row_id}: path does not exist: {row.get('Path')}")
            except ValueError as exc:
                errors.append(str(exc))
            if row.get("AssetType") != "FILE" and not any(
                r.get("Path") == row.get("Path") and r.get("AssetType") == "FILE"
                for r in tables["overlord"]
            ):
                errors.append(f"{row_id}: FILE row required for {row.get('Path')}")
        elif register == "organism":
            errors.extend(f"{row_id}: {error}" for error in rule_errors(row, index))
            status = row.get("Status")
            if status not in OGM_STATUSES:
                errors.append(f"{row_id}: invalid organism status")
            if not row.get("Requirement"):
                errors.append(f"{row_id}: Requirement required")
            if status == "VALIDATED_COMPLETE":
                if not row.get("AcceptanceEvidence", "").strip():
                    errors.append("REFUSAL: Evidence required")
                blocked = [
                    r
                    for r in refs(row.get("BlockedByOGM", ""))
                    if index.get(r, {}).get("Status") != "VALIDATED_COMPLETE"
                ]
                if blocked:
                    errors.append(f"{row_id}: incomplete requirement blockers {';'.join(blocked)}")
            if status == "PACED_REQUIREMENT" and not any(
                row.get(f) for f in ("BlockedByOGM", "PACRefs", "OVRRefs")
            ):
                errors.append(f"{row_id}: PACED_REQUIREMENT needs blocking references")
        else:
            if row.get("ContextPolicy", "") not in {"", "REQUIRED"}:
                errors.append(f"{row_id}: invalid ContextPolicy")
            if row.get("ContextPolicy") == "REQUIRED" and not row.get("UserRequest"):
                errors.append(f"{row_id}: operational nodule requires original UserRequest")
            if row.get("Status") not in {"ACTIVE", "ABSORBED"}:
                errors.append(f"{row_id}: invalid nodule status")
            for field in ("Intent", "AbsorptionCriteria", "CreatedAt", "Lane", "SpawnedPACs"):
                if not row.get(field):
                    errors.append(f"{row_id}: {field} required")
            for asset in refs(row.get("NewAssets", "")):
                try:
                    contained_path(root, asset.split(":", 1)[0])
                except ValueError as exc:
                    errors.append(str(exc))
            if row.get("Status") == "ABSORBED":
                # Absorption is dated history, not a promise that later code cannot regress.
                # Its full criteria are checked by Editor.absorb at the transition.
                if not row.get("AbsorbedAt") or not row.get("AcceptanceEvidence", "").strip():
                    errors.append(f"{row_id}: AbsorbedAt and AcceptanceEvidence required")
    for left, field, right, back in PAIRS:
        for a, f, _b, g in ((left, field, right, back), (right, back, left, field)):
            for row in tables[a]:
                for target in refs(row.get(f, "")):
                    if target in index and row["ID"] not in refs(index[target].get(g, "")):
                        errors.append(f"Asymmetric reference {row['ID']}.{f} -> {target}.{g}")
    counts = Counter(r.get("Assignee") for r in tables["todo"] if r.get("Status") == "DOING")
    for actor, count in counts.items():
        if count > 3:
            errors.append(f"{actor}: more than 3 DOING tasks")
    for register, field in (("todo", "BlockedBy"), ("organism", "BlockedByOGM")):
        edges = {r["ID"]: refs(r.get(field, "")) for r in tables[register]}
        if _has_cycle(edges):
            errors.append("REFUSAL: Circular dependency detected")
    active = [r for r in tables["nodule"] if r.get("Status") == "ACTIVE"]

    def asset_paths(row):
        paths = set()
        for value in refs(row.get("NewAssets", "")):
            try:
                paths.add(str(contained_path(root, value.split(":", 1)[0])).casefold())
            except ValueError:
                pass  # Already reported by row validation.
        return paths

    for i, row in enumerate(active):
        for other in active[i + 1 :]:
            if (
                row.get("Lane") == other.get("Lane")
                or set(refs(row.get("TargetOVR", ""))) & set(refs(other.get("TargetOVR", "")))
                or asset_paths(row) & asset_paths(other)
            ):
                errors.append("REFUSAL: Nodule lane occupied")
    return {"valid": not errors, "errors": list(dict.fromkeys(errors)), "warnings": warnings}


def absorption_errors(row: dict[str, str], tables: dict) -> list[str]:
    """Check machine-verifiable criteria, leaving evidence judgment to the agent."""
    index = {r["ID"]: r for rows in tables.values() for r in rows}
    errors = []
    blocked = [
        r for r in refs(row.get("SpawnedPACs", "")) if index.get(r, {}).get("Status") != "DONE"
    ]
    if blocked:
        errors.append(f"REFUSAL: Blocked by {';'.join(blocked)}")
    for target in refs(row.get("OGMTargets", "")):
        if index.get(target, {}).get("Status") != "VALIDATED_COMPLETE":
            errors.append(f"{row['ID']}: requirement {target} is incomplete")
    for asset in refs(row.get("NewAssets", "")):
        path, _, symbol = asset.partition(":")
        if not any(
            r.get("Path") == path
            and (not symbol or r.get("Symbol") == symbol)
            and "#dead" not in r.get("Tags", "").split()
            for r in tables["overlord"]
        ):
            errors.append(f"{row['ID']}: unregistered new asset {asset}")
    return errors


def _has_cycle(edges: dict[str, list[str]]) -> bool:
    # Kahn's algorithm avoids recursion limits on large task graphs.
    indegree = dict.fromkeys(edges, 0)
    for targets in edges.values():
        for target in targets:
            if target in indegree:
                indegree[target] += 1
    ready = [key for key, count in indegree.items() if count == 0]
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
