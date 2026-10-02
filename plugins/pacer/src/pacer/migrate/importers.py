"""Translate older PACER formats into current rows.

Pure functions: rows in, rows out. Nothing here touches the disk; the original
files are kept verbatim by the caller, so no cell needs to be copied elsewhere.
"""

from __future__ import annotations

import re
from pathlib import Path

from pacer.schema import ID_PATTERN, REGISTERS, empty_row, id_number, refs

STATUS_05 = {"TODO": "TODO", "DOING": "ACTIVE", "REVIEW": "INTEGRATED", "DONE": "DONE"}
NEXT_05 = {
    "inspect": "inspect",
    "implement": "implement",
    "verify": "verify",
    "review": "integrate",
    "absorb": "absorb",
    "resolve": "inspect",
}
STATUS_2 = {
    "todo": "TODO",
    "active": "ACTIVE",
    "integrated": "INTEGRATED",
    "done": "DONE",
    "review": "INTEGRATED",
}
_QUOTED = re.compile(r'"([^"]*)"')


def empty_tables() -> dict[str, list[dict]]:
    return {name: [] for name in REGISTERS}


def _cut(text: str, limit: int) -> str:
    text = (text or "").replace("|", "/").replace("\r", " ").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _first_sentence(text: str, limit: int) -> str:
    text = (text or "").replace("|", "/").replace("\r", " ").replace("\n", " ").strip()
    match = re.match(r"(.+?[.!?])(\s|$)", text)
    return _cut(match.group(1) if match else text, limit)


def _attr(line: str, key: str, default: str = "") -> str:
    match = re.search(rf"\b{re.escape(key)}=(?:\"([^\"]*)\"|(\S+))", line)
    if not match:
        return default
    return match.group(1) if match.group(1) is not None else match.group(2)


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
    absorbed: list[dict],
    project_dir: Path,
    default_tier: str = "prototype",
) -> tuple[dict, dict]:
    """Profile 0.5 rows to current live and archived rows.

    Absorbed nodules and assets whose file is gone go straight to the archive, and
    a requirement recorded as complete is demoted: an old acceptance is not a
    current probe result.
    """
    tables, archive = empty_tables(), empty_tables()
    counters = {"DEC": 0, "PAC": max([0, *(id_number(r["ID"]) for r in old["todo"])])}

    def new_id(prefix: str) -> str:
        counters[prefix] += 1
        return f"{prefix}-{counters[prefix]:03d}"

    def decide(kind: str, subject: str, **fields) -> None:
        row = {"ID": new_id("DEC"), "Kind": kind, "Subject": subject, **fields}
        tables["decision"].append(empty_row("decision", row))

    gone = set()
    for row in old["overlord"]:
        path = row.get("Path", "")
        purpose = _cut(row.get("Purpose", ""), 140)
        tags = " ".join(t for t in row.get("Tags", "").split() if t != "#dead")
        if not purpose and "#unpurposed" not in tags:
            tags = (tags + " #unpurposed").strip()
        asset = empty_row(
            "overlord",
            {
                "ID": row["ID"],
                "Path": path,
                "Symbol": _cut(row.get("Symbol", ""), 120),
                "Kind": row.get("AssetType") or "FILE",
                "Purpose": purpose,
                "Tags": tags,
            },
        )
        if (project_dir / path).is_file():
            tables["overlord"].append(asset)
        else:
            archive["overlord"].append(asset)
            gone.add(row["ID"])

    def live(cell: str) -> str:
        return ";".join(r for r in refs(cell) if r not in gone)

    bound: dict[str, list[str]] = {}
    for row in old["overlord"]:
        for requirement in refs(row.get("OGMRefs", "")):
            bound.setdefault(requirement, []).append(row["ID"])
    for row in old["organism"]:
        status = row.get("Status") or "SCAFFOLD"
        assets = dict.fromkeys([*refs(row.get("OVRRefs", "")), *bound.get(row["ID"], [])])
        tables["organism"].append(
            empty_row(
                "organism",
                {
                    "ID": row["ID"],
                    "Title": _cut(row.get("Title", ""), 80),
                    "Status": "PACED_REQUIREMENT" if status == "VALIDATED_COMPLETE" else status,
                    "Authority": row.get("Authority") or "LEGACY",
                    "Origin": _cut(row.get("OriginText", ""), 400),
                    "Requirement": _cut(row.get("Requirement", ""), 280),
                    "Binds": live(";".join(assets)),
                    "Tags": row.get("Tags", ""),
                },
            )
        )

    groups: dict[str, list[dict]] = {}
    for row in old["todo"]:
        groups.setdefault(row.get("Phase") or "Unphased", []).append(row)
    all_done = all(r.get("Status") == "DONE" for r in old["todo"])
    if old["todo"]:
        tables["todo"].append(
            empty_row(
                "todo",
                {
                    "ID": new_id("PAC"),
                    "Kind": "AREA",
                    "Pos": "A1",
                    "Title": "Imported from profile 0.5",
                    "Status": "DONE" if all_done else "ACTIVE",
                    "Tier": default_tier,
                },
            )
        )
    for number, (name, rows) in enumerate(groups.items(), 1):
        done = all(r.get("Status") == "DONE" for r in rows)
        tables["todo"].append(
            empty_row(
                "todo",
                {
                    "ID": new_id("PAC"),
                    "Kind": "PHASE",
                    "Pos": f"A1.P{number}",
                    "Title": _cut(name, 80),
                    "Status": "DONE" if done else "ACTIVE",
                    "Tier": default_tier,
                    "Exit": _cut(f"imported phase {name}", 140),
                },
            )
        )
        for order, row in enumerate(rows, 1):
            title = row.get("Title", "")
            tables["todo"].append(
                empty_row(
                    "todo",
                    {
                        "ID": row["ID"],
                        "Kind": "PACE",
                        "Pos": f"A1.P{number}.{order:02d}",
                        "Title": _cut(title, 80),
                        "Status": STATUS_05.get(row.get("Status", ""), "TODO"),
                        "Produce": _first_sentence(row.get("DoD") or title, 140),
                        "In": live(row.get("OVRRefs", "")),
                        "Binds": row.get("OGMRefs", ""),
                        "Needs": ";".join(_hard_blockers(row)),
                        "Next": NEXT_05.get(row.get("NextAction", ""), ""),
                        "Tags": row.get("Tags", ""),
                    },
                )
            )
            if row.get("PreviousAttempts"):
                why = _cut(row["PreviousAttempts"], 280)
                decide("FAILED", row["ID"], Why=why, Authority="OBSERVED")
            if row.get("LearningNotes"):
                why = _cut(row["LearningNotes"], 280)
                decide("LESSON", row["ID"], Why=why, Authority="OBSERVED")
            state = row.get("ApprovalState", "")
            if state == "APPROVED":
                decide(
                    "LATCH",
                    row["ID"],
                    Question=_cut("approve " + title, 140),
                    Chosen=_cut("approved: " + title, 140),
                    Why=_cut(row.get("ApprovalEvidence", ""), 280),
                    Authority="USER",
                    Latched="true",
                )
            elif state == "PENDING" or row.get("Phase") == "PROPOSAL":
                question = _cut("approve " + title, 140)
                decide("LATCH", row["ID"], Question=question, Latched="false")

    for row in [*old["nodule"], *absorbed]:
        nodule = empty_row(
            "nodule",
            {
                "ID": row["ID"],
                "Name": _cut(row.get("NoduleName") or row["ID"], 60),
                "Status": row.get("Status") or "ACTIVE",
                "Lane": _cut(row.get("Lane") or row.get("NoduleName") or row["ID"], 40),
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
        if nodule["Status"] == "ABSORBED":
            archive["nodule"].append(nodule)
        else:
            nodule["In"] = live(nodule["In"])
            tables["nodule"].append(nodule)
    return tables, archive


def from_v2(text: str, project_dir: Path) -> tuple[dict, dict, str]:
    """A v2.0.0 `todo.pacer` plan to current rows; returns the project's maturity as its tier."""
    tables, archive = empty_tables(), empty_tables()
    counters = {"PAC": 0, "OVR": 0, "DEC": 0}

    def new_id(prefix: str) -> str:
        counters[prefix] += 1
        return f"{prefix}-{counters[prefix]:03d}"

    def quoted(line: str, fallback: str) -> str:
        match = _QUOTED.search(line)
        return match.group(1) if match else fallback

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
            area_id = new_id("PAC")
            row = {
                "ID": area_id,
                "Kind": "AREA",
                "Pos": f"A{area_n}",
                "Title": _cut(quoted(line, "Area"), 80),
                "Status": STATUS_2.get(_attr(line, "state", "active"), "ACTIVE"),
                "Tier": tier,
            }
            tables["todo"].append(empty_row("todo", row))
        elif line.startswith("PHASE "):
            phase_n, pace_n = phase_n + 1, 0
            phase_id = new_id("PAC")
            row = {
                "ID": phase_id,
                "Kind": "PHASE",
                "Pos": f"A{area_n}.P{phase_n}",
                "Title": _cut(quoted(line, "Phase"), 80),
                "Status": STATUS_2.get(_attr(line, "state", "todo"), "TODO"),
                "Tier": tier,
                "Exit": "imported phase",
            }
            tables["todo"].append(empty_row("todo", row))
        elif line.startswith("PACE "):
            pace_n += 1
            label = line.split(None, 2)[1]
            title = quoted(line, label)
            row = {
                "ID": new_id("PAC"),
                "Kind": "PACE",
                "Pos": f"A{area_n}.P{phase_n}.{pace_n:02d}",
                "Title": _cut(title, 80),
                "Status": STATUS_2.get(_attr(line, "state", "todo"), "TODO"),
                "Produce": _cut(title, 140),
                "Tags": "#" + re.sub(r"[^a-z0-9-]", "-", label.lower()).strip("-"),
            }
            tables["todo"].append(empty_row("todo", row))
        elif line.startswith("EXIT ") and phase_id:
            phase = next(r for r in tables["todo"] if r["ID"] == phase_id)
            phase["Exit"] = _cut(_attr(line, "coherent", phase["Exit"]), 140)
        elif line.startswith("SOURCE "):
            path = quoted(line, "").rstrip("/")
            known = any(r["Path"] == path for r in [*tables["overlord"], *archive["overlord"]])
            if path and not known:
                row = {
                    "ID": new_id("OVR"),
                    "Path": path,
                    "Kind": "FILE",
                    "Purpose": _cut(_attr(line, "role", "source"), 140),
                }
                asset = empty_row("overlord", row)
                target = tables if (project_dir / path).is_file() else archive
                target["overlord"].append(asset)
        elif line.startswith(":nodule "):
            label = line.split(None, 2)[1]
            if not ID_PATTERN.fullmatch(label) or not label.startswith("NDL-"):
                continue
            name = quoted(line, label)
            prefix = f"A{area_n}.P{phase_n}." if phase_id else f"A{area_n}."
            first = next(
                (
                    r["ID"]
                    for r in tables["todo"]
                    if r["Kind"] == "PACE" and r["Pos"].startswith(prefix)
                ),
                "",
            )
            if not first:
                continue
            row = {
                "ID": label,
                "Name": _cut(name, 60),
                "Status": "ACTIVE",
                "Lane": _cut(label.lower(), 40),
                "Request": _cut(name, 400),
                "Intent": _cut(name, 140),
                "Exit": "imported nodule",
                "Spawned": first,
            }
            tables["nodule"].append(empty_row("nodule", row))
        elif line.startswith("+approved "):
            named = line.split()[1]
            subject = named
            if not any(r["ID"] == named for rows in tables.values() for r in rows):
                subject = phase_id or area_id or ""
            if subject:
                row = {
                    "ID": new_id("DEC"),
                    "Kind": "LATCH",
                    "Subject": subject,
                    "Question": _cut(f"approve {named}", 140),
                    "Chosen": "approved",
                    "Authority": "USER",
                    "Latched": "true",
                }
                tables["decision"].append(empty_row("decision", row))
    return tables, archive, tier
