"""Literal PACER 3 columns, vocabularies, limits and grammar."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

VERSION = "3.0"
REGISTERS = ("todo", "overlord", "organism", "nodule", "decision")
LEDGER = "ledger.PACER.jsonl"
HEADERS = {
    "todo": (
        "ID Kind Pos Title Status Tier Produce In Out Binds Needs Probe Exit Next Latch Tags"
    ).split(),
    "overlord": "ID Path Symbol Kind Purpose Tier Binds Latch Tags".split(),
    "organism": "ID Title Status Authority Origin Requirement Binds Probe Evidence Tier Tags".split(),
    "nodule": "ID Name Status Lane Request Intent In Out Targets Spawned Exit Tags".split(),
    "decision": (
        "ID Kind Subject Question Chosen Rejected Why Authority Latched Supersedes Tags"
    ).split(),
}
PREFIX = {"todo": "PAC", "overlord": "OVR", "organism": "OGM", "nodule": "NDL", "decision": "DEC"}
REGISTER_OF = {v: k for k, v in PREFIX.items()}
ID_PATTERN = re.compile(r"(?:PAC|OVR|OGM|NDL|DEC)-[0-9]{3,}[A-Z]*")
REF_PATTERN = re.compile(r"\b(?:PAC|OVR|OGM|NDL|DEC)-[0-9]{3,}[A-Z]*\b")
TAG_PATTERN = re.compile(r"#[a-z][a-z0-9-]*")
POS_PATTERN = re.compile(r"A(\d+)(?:\.P(\d+)(?:\.(\d+))?)?")
# "*" means any prefix.
REF_FIELDS = {
    "todo": {"In": "OVR", "Binds": "OGM", "Needs": "PAC", "Latch": "DEC"},
    "overlord": {"Binds": "OGM", "Latch": "DEC"},
    "organism": {"Binds": "OVR"},
    "nodule": {"In": "OVR", "Targets": "OGM", "Spawned": "PAC"},
    "decision": {"Subject": "*", "Supersedes": "DEC"},
}
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
IMMUTABLE = {"ID", "Kind", "Status", "Evidence", "Latched", "Pos"}


def utc_now() -> str:
    """Return PACER's UTC timestamp representation."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def refs(value: str) -> list[str]:
    """Split the semicolon grammar without interpreting prose."""
    return [part.strip() for part in (value or "").split(";") if part.strip()]


def pos_parts(value: str) -> tuple[int, int | None, int | None]:
    """Decode A1 / A1.P2 / A1.P2.03 into (area, phase, pace)."""
    match = POS_PATTERN.fullmatch(value or "")
    if not match:
        raise ValueError(f"Invalid Pos {value!r}; expected A1, A1.P2 or A1.P2.03")
    area, phase, pace = match.groups()
    return int(area), (int(phase) if phase else None), (int(pace) if pace else None)


def contained_path(root: Path, value: str) -> Path:
    """Reject absolute, traversal, stream and symlink escapes on any host OS."""
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
        raise ValueError(f"Unsafe repository-relative path: {value}")
    resolved = (root / value).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes repository: {value}")
    return resolved


def empty_row(register: str, values: dict[str, str]) -> dict[str, str]:
    """Expand a partial row without discarding extension columns."""
    if register not in HEADERS:
        raise ValueError(f"Unknown register: {register}")
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in values.items()):
        raise ValueError("Row keys and values must be strings")
    return dict.fromkeys(HEADERS[register], "") | values
