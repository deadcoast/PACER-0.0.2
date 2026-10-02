"""Columns, vocabularies, limits and reference grammar of the five registers.

Each relation between rows is stored once, in one direction. The reverse view
(which requirements bind an asset, which decisions sit on a row) is computed when
a card is rendered, so the two directions can never disagree.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

REGISTERS = ("todo", "overlord", "organism", "nodule", "decision")
HEADERS = {
    "todo": [
        "ID",
        "Kind",
        "Pos",
        "Title",
        "Status",
        "Tier",
        "Produce",
        "In",
        "Out",
        "Binds",
        "Needs",
        "Probe",
        "Exit",
        "Next",
        "Tags",
    ],
    "overlord": ["ID", "Path", "Symbol", "Kind", "Purpose", "Tier", "Tags"],
    "organism": [
        "ID",
        "Title",
        "Status",
        "Authority",
        "Origin",
        "Requirement",
        "Binds",
        "Probe",
        "Evidence",
        "Tier",
        "Tags",
    ],
    "nodule": [
        "ID",
        "Name",
        "Status",
        "Lane",
        "Request",
        "Intent",
        "In",
        "Out",
        "Targets",
        "Spawned",
        "Exit",
        "Tags",
    ],
    "decision": [
        "ID",
        "Kind",
        "Subject",
        "Question",
        "Chosen",
        "Rejected",
        "Why",
        "Authority",
        "Latched",
        "Supersedes",
        "Tags",
    ],
}
PREFIX = {"todo": "PAC", "overlord": "OVR", "organism": "OGM", "nodule": "NDL", "decision": "DEC"}
REGISTER_OF = {v: k for k, v in PREFIX.items()}
ID_PATTERN = re.compile(r"(?:PAC|OVR|OGM|NDL|DEC)-[0-9]{3,}[A-Z]*")
REF_PATTERN = re.compile(r"\b(?:PAC|OVR|OGM|NDL|DEC)-[0-9]{3,}[A-Z]*\b")
TAG_PATTERN = re.compile(r"#[a-z][a-z0-9-]*")
POS_PATTERN = re.compile(r"A(\d+)(?:\.P(\d+)(?:\.(\d+))?)?")
# Reference columns and the register prefix they must point at; "*" accepts any.
REF_FIELDS = {
    "todo": {"In": "OVR", "Binds": "OGM", "Needs": "PAC"},
    "overlord": {},
    "organism": {"Binds": "OVR"},
    "nodule": {"In": "OVR", "Targets": "OGM", "Spawned": "PAC"},
    "decision": {"Subject": "*", "Supersedes": "DEC"},
}
# A superseding decision keeps pointing at the decision it replaced after that one is archived.
HISTORICAL_REFS = {("decision", "Supersedes")}
# Columns holding project-relative paths (`path` or `path:symbol`, `;`-separated).
PATH_FIELDS = {"todo": ("Out",), "nodule": ("Out",), "overlord": ("Path",)}
LIMITS = {
    "Title": 80,
    "Produce": 140,
    "Purpose": 140,
    "Requirement": 280,
    "Origin": 400,
    "Why": 280,
    "Chosen": 140,
    "Rejected": 140,
    "Question": 140,
    "Exit": 140,
    "Intent": 140,
    "Request": 400,
    "Probe": 200,
    "Name": 60,
    "Lane": 40,
    "Symbol": 120,
    "Path": 240,
}
TASK_KINDS = ("AREA", "PHASE", "PACE")
TASK_STATUSES = ("TODO", "ACTIVE", "INTEGRATED", "DONE")
TIERS = ("sketch", "prototype", "playable", "integrated", "release", "protected")
OGM_STATUSES = ("SCAFFOLD", "PACED_REQUIREMENT", "VALIDATED_COMPLETE")
AUTHORITIES = ("USER", "OBSERVED", "INFERRED", "UNRESOLVED", "LEGACY")
DEC_KINDS = ("CHOICE", "LATCH", "LESSON", "FAILED")
NEXT_ACTIONS = ("inspect", "implement", "verify", "integrate", "absorb")
OVR_KINDS = ("FILE", "MODULE", "CLASS", "FUNCTION", "METHOD", "CONFIG", "SCHEMA")
NDL_STATUSES = ("ACTIVE", "ABSORBED")
# Columns that only their dedicated operation may change.
IMMUTABLE = {"ID", "Kind", "Status", "Evidence", "Latched", "Pos", "Path"}


def utc_now() -> str:
    """UTC timestamp, second resolution, `Z` suffix."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def refs(value: str) -> list[str]:
    """Split a `;`-separated cell."""
    return [part.strip() for part in (value or "").split(";") if part.strip()]


def id_number(row_id: str) -> int:
    """Numeric part of an ID, ignoring a split suffix such as the `A` in `PAC-012A`."""
    return int(row_id.split("-", 1)[1].rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))


def pos_parts(value: str) -> tuple[int, int | None, int | None]:
    """Decode `A1`, `A1.P2` or `A1.P2.03` into (area, phase, pace)."""
    match = POS_PATTERN.fullmatch(value or "")
    if not match:
        raise ValueError(f"Invalid Pos {value!r}; expected A1, A1.P2 or A1.P2.03")
    area, phase, pace = match.groups()
    return int(area), (int(phase) if phase else None), (int(pace) if pace else None)


def pos_key(row: dict) -> tuple[int, int, int]:
    """Sort key placing an area before its phases and a phase before its paces."""
    try:
        area, phase, pace = pos_parts(row.get("Pos", ""))
    except ValueError:
        return (10**6, 0, 0)
    return (area, phase or 0, pace or 0)


def effective_tier(row: dict | None, phase: dict | None, floor: str) -> str:
    """The most protective of a row's tier, its phase's and the project's; tiers only raise."""
    named = ((row or {}).get("Tier"), (phase or {}).get("Tier"), floor)
    known = [tier for tier in named if tier in TIERS]
    return max(known, key=TIERS.index) if known else TIERS[0]


def contained_path(root: Path, value: str) -> Path:
    """Resolve a project-relative path; reject absolute, traversal and drive forms."""
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        not value
        or "\\" in value
        or ":" in value
        or posix.is_absolute()
        or windows.drive
        or ".." in posix.parts
        or value.startswith("/")
    ):
        raise ValueError(f"Unsafe project-relative path: {value}")
    resolved = (root / value).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes the project: {value}")
    return resolved


def empty_row(register: str, values: dict[str, str]) -> dict[str, str]:
    """A full row for a register from partial values; unknown columns are kept."""
    if register not in HEADERS:
        raise ValueError(f"Unknown register: {register}")
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in values.items()):
        raise ValueError("Row keys and values must be strings")
    return dict.fromkeys(HEADERS[register], "") | values
