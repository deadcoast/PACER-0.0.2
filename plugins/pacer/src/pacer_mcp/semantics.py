"""Versioned operational meaning and directed relations within the four registers."""

from __future__ import annotations

import hashlib
import json
import math
import re

from pacer_mcp.schema import HEADERS, REF_FIELDS, hard_blockers, refs

AUTHORITIES = {"USER", "OBSERVED", "INFERRED", "UNRESOLVED", "LEGACY"}
RULE_TYPES = {"manual", "json_eq", "json_ge", "json_le", "row_eq", "file_sha256"}
NEXT_ACTIONS = {"inspect", "implement", "verify", "review", "absorb", "resolve"}
MEANING_FIELDS = (
    "Requirement",
    "Authority",
    "OriginText",
    "RuleType",
    "RuleSubject",
    "RuleSelector",
    "RuleValue",
    "OVRRefs",
    "BlockedByOGM",
)
LITERAL_FIELDS = {"OriginText", "UserRequest", "ApprovalEvidence", "ApprovalHistory"}
APPROVAL_STATES = {"LEGACY", "PENDING", "APPROVED", "WITHDRAWN"}


def approval_basis(row: dict) -> str:
    """Bind the immutable task identity and DoD plus its declared title."""
    return fingerprint({k: row.get(k, "") for k in ("ID", "Title", "DoD")})


def approval_state(row: dict) -> str:
    """Interpret pre-profile rows conservatively without manufacturing consent."""
    state = row.get("ApprovalState") or "LEGACY"
    if state == "LEGACY" and row.get("Phase") == "PROPOSAL":
        return "PENDING"
    return state


def approval_allowed(row: dict) -> bool:
    """Gate opted-in proposals; LEGACY preserves explicitly labelled compatibility."""
    state = approval_state(row)
    return state == "LEGACY" or (
        state == "APPROVED"
        and row.get("ApprovalBasis") == approval_basis(row)
        and all(row.get(k, "").strip() for k in ("ApprovalEvidence", "ApprovalActor", "ApprovedAt"))
    )


def semantic_schema() -> dict:
    """Expose the operational vocabulary equally to CLI and MCP consumers."""
    return {
        "approval_states": sorted(APPROVAL_STATES),
        "approval": "approval command attests user evidence; PENDING/WITHDRAWN cannot activate; "
        "LEGACY compatibility is not user consent; approval binds ID, Title and immutable DoD",
        "authorities": sorted(AUTHORITIES),
        "rule_types": sorted(RULE_TYPES),
        "next_actions": sorted(NEXT_ACTIONS),
        "rule_contract": {
            "json_eq": "OVR file; RFC6901 selector; exact canonical JSON RuleValue",
            "json_ge": "JSON number >= finite numeric RuleValue; no boolean/string coercion",
            "json_le": "JSON number <= finite numeric RuleValue; no boolean/string coercion",
            "row_eq": "OVR subject; overlord column selector; JSON string RuleValue",
            "file_sha256": "OVR file; empty selector; lowercase SHA-256 JSON string",
            "manual": "Explicit authority/origin; OVRRefs source basis; separate registered report "
            "with requirement, meaning, sources, result PASS and command string array",
        },
        "authority_meanings": {
            "USER": "Requirement directly attributed to preserved user wording",
            "OBSERVED": "Requirement grounded in identified source or measured behavior",
            "INFERRED": "Agent interpretation; never silently promoted to user authority",
            "UNRESOLVED": "Meaning or attribution unresolved; cannot verify",
            "LEGACY": "Historical row awaiting explicit adoption; migration never infers meaning",
        },
        "context_policy": "REQUIRED scopes use current task receipts; pace is separate intake",
        "context_encoding": {
            "default": "pacer-context/2",
            "relations": "edges [source index, kind index, target index]; source/target index "
            "required_ids, kind indexes relations.kinds; preserve order and direction",
            "compatibility": "context encoding=expanded returns original edge objects; "
            "expand_context decodes v2 losslessly; both preserve required facts and receipt",
        },
        "evidence": "PASS/FAIL/UNRESOLVED is observed outcome; CURRENT/STALE/UNBOUND is "
        "accepted-evidence freshness including transitive rule dependencies",
    }


def canonical(value: object) -> str:
    """Encode machine values deterministically without lossy numeric constants."""
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def fingerprint(value: object) -> str:
    """Bind a machine value to its canonical UTF-8 representation."""
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def meaning(row: dict) -> dict:
    """Select the requirement basis independently of workflow history and evidence."""
    return {field: row.get(field, "") for field in MEANING_FIELDS}


def typed_edges(tables: dict) -> list[dict[str, str]]:
    """Emit literal, directed field relations; prose/history never imply an edge."""
    edges = []
    for register, rows in tables.items():
        for row in rows:
            hard = set(hard_blockers(row)) if register == "todo" else set()
            blockers = refs(row.get("BlockedBy", ""))
            kinds = refs(row.get("DependencyType", "")) or ["hard"]
            if len(kinds) == 1:
                kinds *= len(blockers)
            for field in REF_FIELDS[register]:
                for target in refs(row.get(field, "")):
                    relation = field
                    if field == "BlockedBy":
                        relation += ":" + (
                            "hard" if target in hard else kinds[blockers.index(target)]
                        )
                    edges.append({"source": row["ID"], "relation": relation, "target": target})
    return sorted(edges, key=lambda edge: (edge["source"], edge["relation"], edge["target"]))


def rule_errors(row: dict, index: dict) -> list[str]:
    """Validate one rule tuple without inventing meaning for a legacy requirement."""
    errors = []
    authority, kind = row.get("Authority", ""), row.get("RuleType", "")
    if authority and authority not in AUTHORITIES:
        errors.append("invalid Authority")
    if not kind:
        if any(row.get(f) for f in ("RuleSubject", "RuleSelector", "RuleValue")):
            errors.append("RuleType required for rule fields")
        return errors
    if kind not in RULE_TYPES:
        return ["invalid RuleType"]
    if not authority or authority == "LEGACY" or not row.get("OriginText"):
        errors.append("RuleType requires explicit Authority and OriginText")
    subject = row.get("RuleSubject", "")
    selector = row.get("RuleSelector", "")
    if kind == "manual":
        if any(row.get(f) for f in ("RuleSubject", "RuleSelector", "RuleValue")):
            errors.append("manual rules use OVRRefs and an evidence artifact, not predicate fields")
        return errors
    if subject not in index or not subject.startswith("OVR-"):
        errors.append("RuleSubject must resolve to an OVR row")
    if subject not in refs(row.get("OVRRefs", "")):
        errors.append("RuleSubject must also appear in OVRRefs")
    try:
        expected = json.loads(row.get("RuleValue", ""))
        canonical(expected)
    except (ValueError, TypeError):
        return errors + ["RuleValue must be a finite JSON value"]
    if kind in {"json_ge", "json_le"} and (
        type(expected) not in {int, float}
        or (type(expected) is float and not math.isfinite(expected))
    ):
        errors.append("numeric rule requires a finite numeric RuleValue")
    if kind.startswith("json_") and (
        (selector and not selector.startswith("/")) or re.search(r"~(?![01])", selector)
    ):
        errors.append("RuleSelector must be an RFC 6901 JSON pointer")
    if kind == "row_eq" and (selector not in HEADERS["overlord"] or not isinstance(expected, str)):
        errors.append("row_eq needs an overlord column and string RuleValue")
    if kind == "file_sha256" and (
        selector or not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected)
    ):
        errors.append("file_sha256 needs a lowercase SHA-256 value and empty selector")
    return errors
