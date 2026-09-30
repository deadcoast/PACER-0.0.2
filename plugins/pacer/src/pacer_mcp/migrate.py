"""Lossless-by-ledger migration: current meaning into bounded cells, history into events."""

from __future__ import annotations

import re
from pathlib import Path

from pacer_mcp.schema import REGISTERS, empty_row, refs

STATUS_05 = {"TODO": "TODO", "DOING": "ACTIVE", "REVIEW": "INTEGRATED", "DONE": "DONE"}
NEXT_05 = {
    "inspect": "inspect",
    "implement": "implement",
    "verify": "verify",
    "review": "integrate",
    "absorb": "absorb",
    "resolve": "inspect",
}
V2_STATUS = {
    "todo": "TODO",
    "active": "ACTIVE",
    "integrated": "INTEGRATED",
    "done": "DONE",
    "review": "INTEGRATED",
}
_Q = re.compile(r'"([^"]*)"')
OVR_LEGACY = (
    "Exports",
    "Imports",
    "Requires",
    "RequiredBy",
    "PACRefs",
    "NDLRefs",
    "Notes",
    "EvidenceFor",
)
OGM_LEGACY = (
    "AcceptanceEvidence",
    "EvidenceBindings",
    "EvidenceArtifact",
    "RuleType",
    "BlockedByOGM",
    "PACRefs",
    "NDLRefs",
    "AbsorbedFromNDL",
    "Notes",
)
NDL_LEGACY = ("Notes", "AcceptanceEvidence", "CreatedAt", "AbsorbedAt", "ContextPolicy")


def _cut(text: str, limit: int) -> str:
    text = (text or "").replace("|", "/").replace("\r", " ").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _first_sentence(text: str, limit: int) -> str:
    text = (text or "").replace("|", "/").replace("\r", " ").replace("\n", " ").strip()
    match = re.match(r"(.+?[.!?])(\s|$)", text)
    return _cut(match.group(1) if match else text, limit)


def _attr(line: str, key: str, default: str = "") -> str:
    m = re.search(rf"\b{re.escape(key)}=(?:\"([^\"]*)\"|(\S+))", line)
    if not m:
        return default
    return m.group(1) if m.group(1) is not None else m.group(2)


def _empty_tables() -> dict:
    return {name: [] for name in REGISTERS}


def _hard_blockers(row: dict) -> list[str]:
    blockers = refs(row.get("BlockedBy", ""))
    kinds = refs(row.get("DependencyType", "")) or ["hard"]
    if len(kinds) == 1:
        kinds *= len(blockers)
    if len(kinds) != len(blockers):
        return blockers
    return [b for b, k in zip(blockers, kinds, strict=True) if k == "hard"]


def from_05(
    old: dict,
    archived: list[dict],
    default_tier: str = "prototype",
    project_dir: Path | None = None,
) -> tuple[dict, list[dict]]:
    """Profile 0.5 rows to PACER 3 tables plus ledger events carrying every dropped cell."""
    tables, events = _empty_tables(), []
    dec_counter = [0]

    def dec(kind: str, subject: str, **fields) -> str:
        dec_counter[0] += 1
        key = f"DEC-{dec_counter[0]:03d}"
        tables["decision"].append(
            empty_row("decision", {"ID": key, "Kind": kind, "Subject": subject, **fields})
        )
        return key

    ids = [int(r["ID"].split("-")[1].rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")) for r in old["todo"]]
    counter = [max([0, *ids])]

    def pac() -> str:
        counter[0] += 1
        return f"PAC-{counter[0]:03d}"

    groups: dict[str, list[dict]] = {}
    for row in old["todo"]:
        groups.setdefault(row.get("Phase") or "Unphased", []).append(row)
    area_id = pac()
    tables["todo"].append(
        empty_row(
            "todo",
            {
                "ID": area_id,
                "Kind": "AREA",
                "Pos": "A1",
                "Title": "Legacy",
                "Status": "ACTIVE",
                "Tier": default_tier,
            },
        )
    )
    for n, (name, rows) in enumerate(groups.items(), 1):
        phase_id = pac()
        status = "DONE" if all(r.get("Status") == "DONE" for r in rows) else "ACTIVE"
        tables["todo"].append(
            empty_row(
                "todo",
                {
                    "ID": phase_id,
                    "Kind": "PHASE",
                    "Pos": f"A1.P{n}",
                    "Title": _cut(name, 80),
                    "Status": status,
                    "Tier": default_tier,
                    "Exit": _cut(f"migrated phase {name}", 140),
                },
            )
        )
        for k, row in enumerate(rows, 1):
            new = empty_row(
                "todo",
                {
                    "ID": row["ID"],
                    "Kind": "PACE",
                    "Pos": f"A1.P{n}.{k:02d}",
                    "Title": _cut(row.get("Title", ""), 80),
                    "Status": STATUS_05.get(row.get("Status", "TODO"), "TODO"),
                    "Produce": _first_sentence(row.get("DoD", "") or row.get("Title", ""), 140),
                    "In": row.get("OVRRefs", ""),
                    "Binds": row.get("OGMRefs", ""),
                    "Needs": ";".join(_hard_blockers(row)),
                    "Next": NEXT_05.get(row.get("NextAction", ""), ""),
                    "Tags": row.get("Tags", ""),
                },
            )
            latches = []
            if row.get("PreviousAttempts"):
                dec(
                    "FAILED",
                    row["ID"],
                    Why=_cut(row["PreviousAttempts"], 280),
                    Authority="OBSERVED",
                )
            if row.get("LearningNotes"):
                dec("LESSON", row["ID"], Why=_cut(row["LearningNotes"], 280), Authority="OBSERVED")
            state = row.get("ApprovalState", "")
            title = row.get("Title", "")
            if state == "APPROVED":
                latches.append(
                    dec(
                        "LATCH",
                        row["ID"],
                        Question=_cut("approve " + title, 140),
                        Chosen=_cut("approved: " + title, 140),
                        Why=_cut(row.get("ApprovalEvidence", ""), 280),
                        Authority="USER",
                        Latched="true",
                    )
                )
            elif state == "PENDING" or row.get("Phase") == "PROPOSAL":
                latches.append(
                    dec(
                        "LATCH",
                        row["ID"],
                        Question=_cut("approve " + title, 140),
                        Authority="INFERRED",
                        Latched="false",
                    )
                )
            new["Latch"] = ";".join(latches)
            tables["todo"].append(new)
            legacy = {
                k: v for k, v in row.items() if v and k not in {"ID", "Title", "Status", "Tags"}
            }
            events.append(
                {
                    "actor": "migrate",
                    "op": "migrate",
                    "id": row["ID"],
                    "detail": {"from": "0.5", "legacy": legacy},
                }
            )
    for row in old["overlord"]:
        purpose = _cut(row.get("Purpose", ""), 140)
        tags = row.get("Tags", "")
        if not purpose and "#unpurposed" not in tags:
            tags = (tags + " #unpurposed").strip()
        path_value = row.get("Path", "")
        if (
            project_dir is not None
            and "#dead" not in tags
            and not (project_dir / path_value).exists()
        ):
            tags = (tags + " #dead").strip()
        tables["overlord"].append(
            empty_row(
                "overlord",
                {
                    "ID": row["ID"],
                    "Path": row.get("Path", ""),
                    "Symbol": _cut(row.get("Symbol", ""), 120),
                    "Kind": row.get("AssetType", "FILE") or "FILE",
                    "Purpose": purpose,
                    "Binds": row.get("OGMRefs", ""),
                    "Tags": tags,
                },
            )
        )
        legacy = {k: row[k] for k in OVR_LEGACY if row.get(k)}
        if legacy:
            events.append(
                {
                    "actor": "migrate",
                    "op": "migrate",
                    "id": row["ID"],
                    "detail": {"from": "0.5", "legacy": legacy},
                }
            )
    for row in old["organism"]:
        status = row.get("Status", "SCAFFOLD")
        demoted = status == "VALIDATED_COMPLETE"
        tables["organism"].append(
            empty_row(
                "organism",
                {
                    "ID": row["ID"],
                    "Title": _cut(row.get("Title", ""), 80),
                    "Status": "PACED_REQUIREMENT" if demoted else status,
                    "Authority": row.get("Authority") or "LEGACY",
                    "Origin": _cut(row.get("OriginText", ""), 400),
                    "Requirement": _cut(row.get("Requirement", ""), 280),
                    "Binds": row.get("OVRRefs", ""),
                    "Tags": row.get("Tags", ""),
                },
            )
        )
        legacy = {k: row[k] for k in OGM_LEGACY if row.get(k)}
        if demoted:
            legacy["demoted"] = (
                "VALIDATED_COMPLETE->PACED_REQUIREMENT: historical acceptance is not "
                "current proof; run probe"
            )
        events.append(
            {
                "actor": "migrate",
                "op": "migrate",
                "id": row["ID"],
                "detail": {"from": "0.5", "legacy": legacy},
            }
        )
    for row in list(old["nodule"]) + list(archived):
        tables["nodule"].append(
            empty_row(
                "nodule",
                {
                    "ID": row["ID"],
                    "Name": _cut(row.get("NoduleName", ""), 60),
                    "Status": row.get("Status", "ACTIVE"),
                    "Lane": _cut(row.get("Lane") or row.get("NoduleName", ""), 40),
                    "Request": _cut(row.get("UserRequest") or row.get("Intent", ""), 400),
                    "Intent": _cut(row.get("Intent", ""), 140),
                    "In": row.get("TargetOVR", ""),
                    "Out": row.get("NewAssets", ""),
                    "Targets": row.get("OGMTargets", ""),
                    "Spawned": row.get("SpawnedPACs", ""),
                    "Exit": _cut(row.get("AbsorptionCriteria", ""), 140),
                    "Tags": row.get("Tags", ""),
                },
            )
        )
        legacy = {k: row[k] for k in NDL_LEGACY if row.get(k)}
        events.append(
            {
                "actor": "migrate",
                "op": "migrate",
                "id": row["ID"],
                "detail": {"from": "0.5", "legacy": legacy},
            }
        )
    return tables, events


def from_v2(text: str, project_dir: Path) -> tuple[dict, list[dict]]:
    """v2.0.0 todo.PACER plan text to PACER 3 tables; writes .MIVIM.spec if absent."""
    tables, events = _empty_tables(), []
    counter = {"PAC": 0, "OVR": 0, "DEC": 0}

    def nid(prefix: str) -> str:
        counter[prefix] += 1
        return f"{prefix}-{counter[prefix]:03d}"

    tier, area_n, phase_n, pace_n = "prototype", 0, 0, 0
    area_id = phase_id = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("PROJECT "):
            tier = _attr(line, "maturity", tier)
        elif line.startswith("GLOBAL "):
            area_n, phase_n = area_n + 1, 0
            m = _Q.search(line)
            area_id = nid("PAC")
            tables["todo"].append(
                empty_row(
                    "todo",
                    {
                        "ID": area_id,
                        "Kind": "AREA",
                        "Pos": f"A{area_n}",
                        "Title": _cut(m.group(1) if m else "Area", 80),
                        "Status": V2_STATUS.get(_attr(line, "state", "active"), "ACTIVE"),
                        "Tier": tier,
                    },
                )
            )
        elif line.startswith("PHASE "):
            phase_n, pace_n = phase_n + 1, 0
            m = _Q.search(line)
            phase_id = nid("PAC")
            tables["todo"].append(
                empty_row(
                    "todo",
                    {
                        "ID": phase_id,
                        "Kind": "PHASE",
                        "Pos": f"A{area_n}.P{phase_n}",
                        "Title": _cut(m.group(1) if m else "Phase", 80),
                        "Status": V2_STATUS.get(_attr(line, "state", "todo"), "TODO"),
                        "Tier": tier,
                        "Exit": "migrated phase",
                    },
                )
            )
        elif line.startswith("PACE "):
            pace_n += 1
            parts = line.split(None, 2)
            m = _Q.search(line)
            title = m.group(1) if m else parts[1]
            tag = "#" + re.sub(r"[^a-z0-9-]", "-", parts[1].lower()).strip("-")
            tables["todo"].append(
                empty_row(
                    "todo",
                    {
                        "ID": nid("PAC"),
                        "Kind": "PACE",
                        "Pos": f"A{area_n}.P{phase_n}.{pace_n:02d}",
                        "Title": _cut(title, 80),
                        "Status": V2_STATUS.get(_attr(line, "state", "todo"), "TODO"),
                        "Produce": _cut(title, 140),
                        "Tags": tag,
                    },
                )
            )
        elif line.startswith("EXIT ") and phase_id:
            row = next(r for r in tables["todo"] if r["ID"] == phase_id)
            row["Exit"] = _cut(_attr(line, "coherent", row["Exit"]), 140)
        elif line.startswith("SOURCE "):
            m = _Q.search(line)
            if m and not any(r["Path"] == m.group(1).rstrip("/") for r in tables["overlord"]):
                tables["overlord"].append(
                    empty_row(
                        "overlord",
                        {
                            "ID": nid("OVR"),
                            "Path": m.group(1).rstrip("/"),
                            "Kind": "FILE",
                            "Purpose": _cut(_attr(line, "role", "source"), 140),
                        },
                    )
                )
        elif line.startswith(":nodule "):
            parts = line.split(None, 2)
            m = _Q.search(line)
            name = m.group(1) if m else parts[1]
            prefix = f"A{area_n}.P{phase_n}." if phase_id else f"A{area_n}"
            first_pace = next(
                (
                    r["ID"]
                    for r in tables["todo"]
                    if r["Kind"] == "PACE" and r["Pos"].startswith(prefix)
                ),
                "",
            )
            tables["nodule"].append(
                empty_row(
                    "nodule",
                    {
                        "ID": parts[1],
                        "Name": _cut(name, 60),
                        "Status": "ACTIVE",
                        "Lane": _cut(parts[1].lower(), 40),
                        "Request": _cut(name, 400),
                        "Intent": _cut(name, 140),
                        "Exit": "migrated nodule",
                        "Spawned": first_pace,
                    },
                )
            )
        elif line.startswith("+approved "):
            subject = line.split()[1]
            tables["decision"].append(
                empty_row(
                    "decision",
                    {
                        "ID": nid("DEC"),
                        "Kind": "LATCH",
                        "Subject": subject,
                        "Question": _cut(f"approve {subject}", 140),
                        "Chosen": "approved",
                        "Authority": "USER",
                        "Latched": "true",
                    },
                )
            )
    for row in tables["overlord"]:
        if not (project_dir / row["Path"]).exists():
            row["Tags"] = (row["Tags"] + " #dead").strip()
    spec = project_dir / ".MIVIM.spec"
    if not spec.exists():
        spec.write_text(
            f'[project]\nname = "{project_dir.name}"\ntier = "{tier}"\n', encoding="utf-8"
        )
    events.append(
        {"actor": "migrate", "op": "migrate", "id": "-", "detail": {"from": "v2", "tier": tier}}
    )
    return tables, events
