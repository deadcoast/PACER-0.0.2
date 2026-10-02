"""Compile bounded card frames for harness events.

A frame is a head line followed by cards. The spine (focus, its phase, the
decisions on them) is always present; the rest is added in relevance order until
the byte budget is spent, and a trailer counts what was left out. A frame never
fails on budget and never renders a card it will not emit.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from pacer.cards import card
from pacer.probe import bound_paths, file_digests, freshness, parse_evidence
from pacer.rank import rank
from pacer.schema import REF_PATTERN, REGISTERS, TAG_PATTERN, pos_key, pos_parts, refs

# Anything path-shaped; a token only counts when it equals a registered asset path.
PATH_TOKEN = re.compile(r"[\w./-]+")
MAX_USED_BY = 8
NEXT_PACES = 5


def phase_of(row: dict | None, tables: dict) -> dict | None:
    """The PHASE row governing a PACE; a PHASE governs itself."""
    if row is None:
        return None
    try:
        area, phase, pace = pos_parts(row.get("Pos", ""))
    except ValueError:
        return None
    if pace is None:
        return row if phase is not None else None
    for other in tables["todo"]:
        if other.get("Kind") == "PHASE" and other.get("Pos") == f"A{area}.P{phase}":
            return other
    return None


def active_pace(tables: dict, store) -> dict | None:
    """The single ACTIVE pace, else the one most recently worked, else the first by position."""
    active = [r for r in tables["todo"] if r.get("Kind") == "PACE" and r.get("Status") == "ACTIVE"]
    if len(active) <= 1:
        return active[0] if active else None
    ids = {r["ID"]: r for r in active}
    for entry in reversed(store.ledger_read(None, 200)):
        if entry.get("op") in {"touch", "status", "checkpoint"} and entry.get("id") in ids:
            return ids[entry["id"]]
    return min(active, key=pos_key)


def bound_requirements(phase: dict | None, pace: dict | None) -> list[str]:
    """Requirements a pace answers to: its phase's, then its own."""
    keys: list[str] = []
    for row in (phase, pace):
        if row:
            keys += refs(row.get("Binds", ""))
    return list(dict.fromkeys(keys))


class Compiler:
    """One read of the registers, with the reverse views a card needs."""

    def __init__(self, tables: dict, root: Path, store, provider, config: dict):
        self.tables, self.root, self.store = tables, root, store
        self.provider, self.config = provider, config
        self.index = {r["ID"]: (reg, r) for reg in REGISTERS for r in tables.get(reg, [])}
        # A decision that another one supersedes is history: never delivered, still queryable.
        self.superseded = {r["Supersedes"] for r in tables["decision"] if r.get("Supersedes")}
        self.decisions: dict[str, list[str]] = {}
        self.latches: dict[str, list[str]] = {}
        for row in tables["decision"]:
            if row["ID"] in self.superseded:
                continue
            for subject in refs(row.get("Subject", "")):
                self.decisions.setdefault(subject, []).append(row["ID"])
                if row.get("Kind") == "LATCH":
                    self.latches.setdefault(subject, []).append(row["ID"])
        self.bound_by: dict[str, list[str]] = {}
        for row in tables["organism"]:
            for asset in refs(row.get("Binds", "")):
                self.bound_by.setdefault(asset, []).append(row["ID"])

    # -- cards ---------------------------------------------------------------
    def render(self, key: str, flags: Iterable[str] = ()) -> str:
        register, row = self.index[key]
        extras: dict[str, str] = dict.fromkeys(flags, "1")
        if register == "organism":
            extras["Evidence"] = self._evidence(row)
        elif register == "overlord":
            extras["bound-by"] = ";".join(self.bound_by.get(key, []))
            extras["used-by"] = self._used_by(row)
            if not (self.root / row["Path"]).is_file():
                extras["missing"] = "1"
        if register in {"overlord", "todo"}:
            extras["latch"] = ";".join(self.latches.get(key, []))
        return card(register, row, extras)

    def _evidence(self, row: dict) -> str:
        parsed = parse_evidence(row.get("Evidence", ""))
        if parsed is None:
            return "UNBOUND"
        state = freshness(row, self.tables, self.root)
        text = f"rev:{parsed['rev']} exit:{parsed['exit']} at:{parsed['at'][:10]}"
        moved = self._moved(row) if state == "STALE" else ""
        return f"{text} {state}" + (f"({moved})" if moved else "")

    def _moved(self, row: dict) -> str:
        """Bound files that differ from the probe run behind the evidence, from its ledger event."""
        recorded = next(
            (
                event["detail"].get("files")
                for event in reversed(self.store.ledger_read(row["ID"], 20))
                if event.get("op") == "probe"
                and event.get("detail", {}).get("evidence") == row["Evidence"]
            ),
            None,
        )
        if not isinstance(recorded, dict):
            return ""
        current = file_digests(self.root, bound_paths(row, self.tables))
        changed = sorted(p for p in {*recorded, *current} if recorded.get(p) != current.get(p))
        return ",".join(changed[:3]) + (f" +{len(changed) - 3}" if len(changed) > 3 else "")

    def _used_by(self, row: dict) -> str:
        if row.get("Kind") != "FILE":
            return ""
        return _shorten(sorted(self.provider.users(row["Path"])))

    def decisions_for(self, subjects: Iterable[str]) -> list[str]:
        keys: list[str] = []
        for subject in subjects:
            keys += self.decisions.get(subject, [])
        return list(dict.fromkeys(keys))

    # -- assembly ------------------------------------------------------------
    def head(self, pace: dict | None) -> str:
        project, tier = self.config["project"], self.config["tier"]
        return f"PACER {project} tier={tier} pace={pace['ID'] if pace else 'none'}"

    def fit(self, spine: list[str], keys: Iterable[str], budget: int, focus: str) -> str:
        """Spine always; then cards in order while they fit; a trailer counts the rest."""
        out = list(spine)
        used = sum(len(line.encode("utf-8")) + 1 for line in out)
        dropped, full = 0, False
        for key in keys:
            if key in self.superseded:
                continue
            if full:
                dropped += 1
                continue
            line = self.render(key)
            size = len(line.encode("utf-8")) + 1
            if used + size > budget:
                full = True
                dropped += 1
                continue
            out.append(line)
            used += size
        if dropped:
            out.append(f"+{dropped} more: pacer_q {focus}")
        return "\n".join(out)

    def _unfinished(self, keys: Iterable[str]) -> list[str]:
        """Drop finished paces from a ranked fill: they are history, still reachable by ID."""

        def finished(key: str) -> bool:
            register, row = self.index[key]
            return register == "todo" and row["Kind"] == "PACE" and row["Status"] == "DONE"

        return [key for key in keys if not finished(key)]

    def session(self) -> str:
        todo = sorted(self.tables["todo"], key=pos_key)
        pace = active_pace(self.tables, self.store)
        # Open work: a pace waiting to start, in hand, or integrated and not yet closed.
        open_paces = [r for r in todo if r["Kind"] == "PACE" and r["Status"] != "DONE"]
        phase = (
            phase_of(pace, self.tables)
            or next((r for r in todo if r["Kind"] == "PHASE" and r["Status"] == "ACTIVE"), None)
            or (phase_of(open_paces[0], self.tables) if open_paces else None)
        )
        area = None
        if phase:
            number = pos_parts(phase["Pos"])[0]
            area = next((r for r in todo if r["Kind"] == "AREA" and r["Pos"] == f"A{number}"), None)
        spine_keys = [r["ID"] for r in (area, phase, pace) if r]
        requirements = [k for k in bound_requirements(phase, pace) if k in self.index]
        subjects = [*spine_keys, *(refs(pace["In"]) if pace else []), *requirements]
        spine_keys += self.decisions_for(subjects)
        spine_keys = list(dict.fromkeys(spine_keys))
        spine = [self.head(pace), *(self.render(k) for k in spine_keys)]
        upcoming = [r["ID"] for r in open_paces if r is not pace]
        if phase:
            in_phase = [k for k in upcoming if phase_of(self.index[k][1], self.tables) is phase]
            upcoming = in_phase or upcoming
        focus = [pace["ID"]] if pace else ([phase["ID"]] if phase else [])
        if not pace:
            spine.append(_idle_line(bool(self.index), len(open_paces)))
        ranked = [k for _, k in rank(self.tables, self.provider, focus)] if focus else []
        ordered = dict.fromkeys([*requirements, *upcoming[:NEXT_PACES], *self._unfinished(ranked)])
        keys = [k for k in ordered if k not in spine_keys]
        budget = self.config["budgets"]["session"]
        return self.fit(spine, keys, budget, focus[0] if focus else "todo")

    def edit(self, path: str) -> str:
        pace = active_pace(self.tables, self.store)
        assets = [r for r in self.tables["overlord"] if r.get("Path") == path]
        subjects = [r["ID"] for r in assets]
        spine = [self.head(pace)]
        if assets:
            flags = () if self._in_pace(pace, path, subjects) else ("OFF-PACE",)
            spine += [self.render(key, flags) for key in subjects]
        else:
            users = _shorten(sorted(self.provider.users(path)))
            spine.append(f"OVR - {path} unregistered" + (f" | used-by: {users}" if users else ""))
        requirements = list(dict.fromkeys(k for s in subjects for k in self.bound_by.get(s, [])))
        decisions = self.decisions_for([*subjects, *requirements])
        spine += [self.render(k) for k in [*requirements, *decisions]]
        seen = {*subjects, *requirements, *decisions}
        ranked = [k for _, k in rank(self.tables, self.provider, subjects)] if subjects else []
        ordered = dict.fromkeys([*([pace["ID"]] if pace else []), *self._unfinished(ranked)])
        keys = [k for k in ordered if k not in seen]
        return self.fit(
            spine, keys, self.config["budgets"]["edit"], subjects[0] if subjects else path
        )

    def _in_pace(self, pace: dict | None, path: str, assets: list[str]) -> bool:
        if pace is None:
            return True
        planned = [o.split(":", 1)[0] for o in refs(pace.get("Out", ""))]
        return path in planned or bool(set(assets) & set(refs(pace.get("In", ""))))

    def prompt(self, text: str) -> str:
        """Cards for whatever the prompt names; empty when it names nothing."""
        ids = [i for i in REF_PATTERN.findall(text) if i in self.index]
        mentioned = {token.rstrip(".") for token in PATH_TOKEN.findall(text)}
        paths = sorted(r["ID"] for r in self.tables["overlord"] if r.get("Path") in mentioned)
        tags = set(TAG_PATTERN.findall(text))
        tagged = [
            r["ID"]
            for reg in REGISTERS
            for r in self.tables[reg]
            if tags & set(r.get("Tags", "").split())
        ]
        keys = list(dict.fromkeys([*ids, *paths, *tagged]))
        if not keys:
            return ""
        return self.fit([], keys, self.config["budgets"]["prompt"], keys[0])


def _shorten(paths: list[str]) -> str:
    shown = ", ".join(paths[:MAX_USED_BY])
    extra = len(paths) - MAX_USED_BY
    return shown + (f" (+{extra})" if extra > 0 else "")


def _idle_line(has_rows: bool, open_paces: int) -> str:
    if not has_rows:
        return "empty registers: pace the first request with pacer_write op pace (skill: pacer)"
    if open_paces:
        return f"no active pace: {open_paces} open; start one with op status <PAC> ACTIVE"
    return "no open work: pace the next request with op pace"
