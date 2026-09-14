"""Literal PACER columns, reference relations, and grammar."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

VERSION = "0.2"
HEADERS = {
    "todo": "ID Title Phase Status Priority Assignee DoD BlockedBy DependencyType "
    "DependencyReason UnblockingStrategy Context Instructions ExpectedOutput ValidationCriteria "
    "ErrorHandling PreviousAttempts RelatedWork LearningNotes Notes StartedAt DoneAt "
    "OVRRefs OGMRefs NDLRefs Tags UpdatedAt".split(),
    "overlord": "ID AssetType Path Symbol Purpose Exports Imports Requires RequiredBy OGMRefs "
    "PACRefs NDLRefs Tags Notes UpdatedAt".split(),
    "organism": "ID Title Domain Status Requirement AcceptanceEvidence OVRRefs PACRefs "
    "BlockedByOGM AbsorbedFromNDL Tags Notes UpdatedAt NDLRefs".split(),
    "nodule": "ID NoduleName Intent Status TargetOVR NewAssets OGMTargets SpawnedPACs "
    "AbsorptionCriteria Tags Notes CreatedAt AbsorbedAt Lane AcceptanceEvidence".split(),
}
PREFIX = {"todo": "PAC", "overlord": "OVR", "organism": "OGM", "nodule": "NDL"}
ID_PATTERN = re.compile(r"(?:PAC|OVR|OGM|NDL)-[0-9]{3,}[A-Z]*")
REF_PATTERN = re.compile(r"\b(?:PAC|OVR|OGM|NDL)-[0-9]{3,}[A-Z]*\b")
TAG_PATTERN = re.compile(r"#[a-z][a-z0-9-]*")
REF_FIELDS = {
    "todo": {"BlockedBy": "PAC", "OVRRefs": "OVR", "OGMRefs": "OGM", "NDLRefs": "NDL"},
    "overlord": {
        "Requires": "OVR",
        "RequiredBy": "OVR",
        "OGMRefs": "OGM",
        "PACRefs": "PAC",
        "NDLRefs": "NDL",
    },
    "organism": {
        "OVRRefs": "OVR",
        "PACRefs": "PAC",
        "BlockedByOGM": "OGM",
        "AbsorbedFromNDL": "NDL",
        "NDLRefs": "NDL",
    },
    "nodule": {"TargetOVR": "OVR", "OGMTargets": "OGM", "SpawnedPACs": "PAC"},
}
# (source register, column, target register, reciprocal column)
PAIRS = [
    ("overlord", "Requires", "overlord", "RequiredBy"),
    ("overlord", "OGMRefs", "organism", "OVRRefs"),
    ("overlord", "PACRefs", "todo", "OVRRefs"),
    ("overlord", "NDLRefs", "nodule", "TargetOVR"),
    ("todo", "OGMRefs", "organism", "PACRefs"),
    ("todo", "NDLRefs", "nodule", "SpawnedPACs"),
    ("organism", "NDLRefs", "nodule", "OGMTargets"),
]
TODO_TRANSITIONS = {
    ("TODO", "DOING"),
    ("DOING", "REVIEW"),
    ("DOING", "TODO"),
    ("REVIEW", "DONE"),
    ("REVIEW", "DOING"),
}
OGM_STATUSES = {"SCAFFOLD", "PACED_REQUIREMENT", "VALIDATED_COMPLETE"}
HISTORY = {"Notes", "LearningNotes", "PreviousAttempts"}


def utc_now() -> str:
    """Return PACER's UTC timestamp representation."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def refs(value: str) -> list[str]:
    """Split the semicolon grammar without interpreting prose."""
    return [part.strip() for part in value.split(";") if part.strip()]


def hard_blockers(row: dict[str, str]) -> list[str]:
    """Resolve uniform or position-aligned dependency types; blank means hard."""
    blockers = refs(row.get("BlockedBy", ""))
    kinds = refs(row.get("DependencyType", "")) or ["hard"]
    if any(kind not in {"hard", "soft", "optional"} for kind in kinds):
        raise ValueError(f"Invalid DependencyType on {row['ID']}")
    if len(kinds) > 1 and len(kinds) != len(blockers):
        raise ValueError(f"DependencyType count mismatch on {row['ID']}")
    if len(kinds) == 1:
        kinds *= len(blockers)
    return [item for item, kind in zip(blockers, kinds, strict=True) if kind == "hard"]


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
