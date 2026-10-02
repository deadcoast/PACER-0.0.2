"""The write lexicon: every mutation is an event; registers hold current state only."""

from __future__ import annotations

from pathlib import Path

from pacer.probe import freshness
from pacer.schema import (
    HEADERS,
    HISTORICAL_REFS,
    IMMUTABLE,
    LIMITS,
    OGM_STATUSES,
    PATH_FIELDS,
    PREFIX,
    REF_FIELDS,
    REGISTER_OF,
    REGISTERS,
    TASK_STATUSES,
    contained_path,
    empty_row,
    id_number,
    pos_parts,
    refs,
)

DEFAULTS = {
    "todo": {"Status": "TODO", "Kind": "PACE"},
    "organism": {"Status": "SCAFFOLD", "Authority": "INFERRED"},
    "overlord": {"Kind": "FILE"},
    "nodule": {"Status": "ACTIVE"},
    "decision": {"Authority": "INFERRED"},
}


class Editor:
    """Apply lexicon operations to an in-memory snapshot and collect ledger events."""

    def __init__(self, tables: dict, archive: dict, actor: str, root: Path):
        self.tables, self.archive, self.actor, self.root = tables, archive, actor, root
        self.changed: set[str] = set()
        self.events: list[dict] = []

    # -- helpers -------------------------------------------------------------
    def find(self, key: str) -> tuple[str, dict]:
        register = REGISTER_OF.get(key.split("-")[0], "")
        for row in self.tables.get(register, []):
            if row["ID"] == key:
                return register, row
        if any(row["ID"] == key for row in self.archive.get(register, [])):
            raise ValueError(f"REFUSAL: {key} is archived")
        raise ValueError(f"REFUSAL: Unknown ID {key}")

    def _taken(self, key: str) -> bool:
        return any(
            row["ID"] == key
            for register in REGISTERS
            for row in (*self.tables[register], *self.archive[register])
        )

    def next_id(self, register: str) -> str:
        """Next unused number; archived rows keep their numbers forever."""
        rows = (*self.tables[register], *self.archive[register])
        return f"{PREFIX[register]}-{max([0, *(id_number(r['ID']) for r in rows)]) + 1:03d}"

    def event(self, op: str, key: str, detail: dict | None = None) -> None:
        self.events.append({"actor": self.actor, "op": op, "id": key, "detail": detail or {}})
        self.changed.add(key)

    def _check_text(self, key: str, cells: dict) -> None:
        for field, value in cells.items():
            if not isinstance(value, str):
                raise ValueError(f"{key}: {field} must be a string")
            if "|" in value or "\n" in value or "\r" in value:
                raise ValueError(f"{key}: {field} contains | or a newline")
            if field in LIMITS and len(value) > LIMITS[field]:
                raise ValueError(f"{key}: {field} exceeds {LIMITS[field]} characters")

    # -- dispatch ------------------------------------------------------------
    def execute(self, op: dict) -> None:
        handler = getattr(self, f"op_{op.get('op')}", None)
        if handler is None:
            raise ValueError(f"Unknown operation {op.get('op')}")
        handler(op)

    def op_add(self, op: dict) -> None:
        register, values = op["register"], dict(op["row"])
        if register not in HEADERS:
            raise ValueError(f"Unknown register {register}")
        unknown = set(values) - set(HEADERS[register])
        if unknown:
            raise ValueError(f"{register}: unknown columns {','.join(sorted(unknown))}")
        key = values.get("ID") or self.next_id(register)
        if self._taken(key):
            raise ValueError(f"Duplicate ID {key}")
        row = empty_row(register, {**values, "ID": key})
        for field, value in DEFAULTS.get(register, {}).items():
            row[field] = row[field] or value
        if register == "decision" and row["Kind"] == "LATCH" and not row["Latched"]:
            row["Latched"] = "false"
        self._check_text(key, row)
        self.tables[register].append(row)
        self.event("add", key, {"register": register})

    def op_set(self, op: dict) -> None:
        register, row = self.find(op["id"])
        fields = dict(op["fields"])
        blocked = set(fields) & IMMUTABLE
        if blocked:
            raise ValueError(
                f"{op['id']}: {','.join(sorted(blocked))} immutable via set; "
                "use status, move, latch, probe or repath"
            )
        unknown = set(fields) - set(HEADERS[register])
        if unknown:
            raise ValueError(f"{op['id']}: unknown columns {','.join(sorted(unknown))}")
        self._check_text(op["id"], fields)
        before = {k: row[k] for k in fields}
        row.update(fields)
        self.event("set", op["id"], {"before": before, "after": fields})

    def op_link(self, op: dict) -> None:
        register, row = self.find(op["id"])
        field, target = op["field"], op["target"]
        if field not in REF_FIELDS[register]:
            raise ValueError(f"{op['id']}: {field} is not a reference column")
        self.find(target)
        current = refs(row[field])
        if op.get("remove"):
            current = [c for c in current if c != target]
        elif target not in current:
            current.append(target)
        row[field] = ";".join(current)
        name = "unlink" if op.get("remove") else "link"
        self.event(name, op["id"], {"field": field, "target": target})

    def op_move(self, op: dict) -> None:
        register, row = self.find(op["id"])
        if register != "todo":
            raise ValueError("move applies to todo rows")
        pos_parts(op["pos"])
        self.event("move", op["id"], {"from": row["Pos"], "to": op["pos"]})
        row["Pos"] = op["pos"]

    def op_status(self, op: dict) -> None:
        register, row = self.find(op["id"])
        status = op["status"]
        if register == "nodule":
            raise ValueError("a nodule changes status only through pace and absorb")
        allowed = {"todo": TASK_STATUSES, "organism": OGM_STATUSES}.get(register)
        if allowed is None or status not in allowed:
            raise ValueError(f"{op['id']}: illegal status {status}")
        complete = register == "organism" and status == "VALIDATED_COMPLETE"
        if complete and freshness(row, self.tables, self.root) != "CURRENT":
            raise ValueError(
                "REFUSAL: Evidence required (run probe; evidence must be exit:0 and current)"
            )
        if register == "todo" and status == "DONE":
            blocked = [
                t for t in refs(row.get("Needs", "")) if self.find(t)[1].get("Status") != "DONE"
            ]
            if blocked:
                raise ValueError(f"REFUSAL: Blocked by {';'.join(blocked)}")
        self.event("status", op["id"], {"from": row["Status"], "to": status})
        row["Status"] = status

    def op_latch(self, op: dict) -> None:
        register, row = self.find(op["id"])
        if register != "decision" or row.get("Kind") != "LATCH":
            raise ValueError(f"{op['id']}: latch applies to DEC LATCH rows")
        value = op["latched"]
        if value not in {"true", "false"}:
            raise ValueError("latched must be 'true' or 'false'")
        if value == "true":
            row["Authority"] = "USER"
        row["Latched"] = value
        self.event("latch", op["id"], {"latched": value, "evidence": op.get("evidence", "")})

    def op_pace(self, op: dict) -> None:
        """Admit scope: one nodule with its requirements, decisions and work rows."""
        nodule = dict(op["nodule"])
        tasks = [dict(t) for t in op.get("tasks", [])]
        requirements = [dict(r) for r in op.get("requirements", [])]
        decisions = [dict(d) for d in op.get("decisions", [])]
        for register, rows in (("organism", requirements), ("todo", tasks)):
            for row in rows:
                row.setdefault("ID", "")
                if not row["ID"]:
                    row["ID"] = self.next_id(register)
                self.op_add({"op": "add", "register": register, "row": row})
        for row in decisions:
            self.op_add({"op": "add", "register": "decision", "row": row})
        spawned = [t["ID"] for t in tasks if t.get("Kind", "PACE") == "PACE"]
        spawned += refs(nodule.get("Spawned", ""))
        nodule["Spawned"] = ";".join(dict.fromkeys(spawned))
        targets = [r["ID"] for r in requirements] + refs(nodule.get("Targets", ""))
        nodule["Targets"] = ";".join(dict.fromkeys(targets))
        nodule["Status"] = "ACTIVE"
        self.op_add({"op": "add", "register": "nodule", "row": nodule})

    def op_absorb(self, op: dict) -> None:
        """Close a nodule whose exit holds; it and the decisions about it leave the live web."""
        register, row = self.find(op["id"])
        if register != "nodule":
            raise ValueError(f"{op['id']}: absorb applies to nodules")
        problems = []
        for key in refs(row.get("Spawned", "")):
            if self.find(key)[1].get("Status") != "DONE":
                problems.append(f"{key} not DONE")
        for key in refs(row.get("Targets", "")):
            target = self.find(key)[1]
            complete = target.get("Status") == "VALIDATED_COMPLETE"
            if not complete or freshness(target, self.tables, self.root) != "CURRENT":
                problems.append(f"{key} incomplete or stale")
        for item in refs(row.get("Out", "")):
            path = item.split(":", 1)[0]
            if not any(r["Path"] == path for r in self.tables["overlord"]):
                problems.append(f"{item} unregistered")
        if problems:
            raise ValueError(f"{op['id']}: incomplete: " + "; ".join(problems))
        row["Status"] = "ABSORBED"
        self.event("absorb", op["id"], {})
        self._retire({op["id"]}, cascade=True, reason="absorbed")

    def op_archive(self, op: dict) -> None:
        """Retire rows from the live web. An AREA or PHASE takes its subtree with it."""
        selected: set[str] = set()
        for key in op["ids"]:
            register, row = self.find(key)
            selected.add(key)
            if register == "nodule":
                raise ValueError(f"{key}: an ACTIVE nodule is closed with absorb, not archive")
            if register == "todo" and row["Kind"] in {"AREA", "PHASE"}:
                prefix = row["Pos"] + "."
                selected |= {r["ID"] for r in self.tables["todo"] if r["Pos"].startswith(prefix)}
        open_work = sorted(
            r["ID"]
            for r in self.tables["todo"]
            if r["ID"] in selected and r["Kind"] == "PACE" and r["Status"] != "DONE"
        )
        if open_work:
            raise ValueError(f"REFUSAL: cannot archive open work {';'.join(open_work)}")
        retired = self._retire(selected, cascade=op.get("cascade", True), reason="archive")
        self.event("archive", sorted(op["ids"])[0], {"ids": retired})

    def op_repath(self, op: dict) -> None:
        """Follow a moved file or directory in every path-bearing cell."""
        old, new = op["from"], op["to"]
        prefix = old.endswith("/")
        if prefix != new.endswith("/"):
            raise ValueError("repath: give two files, or two directories ending in /")
        contained_path(self.root, new.rstrip("/"))

        def follow(path: str) -> str:
            if prefix:
                return new + path[len(old) :] if path.startswith(old) else path
            return new if path == old else path

        count = 0
        for register, fields in PATH_FIELDS.items():
            for row in self.tables[register]:
                for field in fields:
                    items = [row[field]] if field == "Path" else refs(row[field])
                    moved = []
                    for item in items:
                        path, sep, symbol = item.partition(":")
                        moved.append(follow(path) + sep + symbol)
                    if moved != items:
                        row[field] = moved[0] if field == "Path" else ";".join(moved)
                        self.changed.add(row["ID"])
                        count += 1
        if not count:
            raise ValueError(f"repath: no row references {old}")
        self.events.append(
            {
                "actor": self.actor,
                "op": "repath",
                "id": "-",
                "detail": {"from": old, "to": new, "cells": count},
            }
        )

    def op_touch(self, op: dict) -> None:
        """Record an edit against the active pace; an unknown file becomes an unpurposed asset."""
        path, pace = op["path"], op.get("pace", "")
        registered = any(r["Path"] == path for r in self.tables["overlord"])
        detail: dict = {"path": path}
        if not registered:
            key = self.next_id("overlord")
            row = {"ID": key, "Path": path, "Kind": "FILE", "Tags": "#unpurposed"}
            self.op_add({"op": "add", "register": "overlord", "row": row})
            detail["new"] = key
            if pace:
                _, work = self.find(pace)
                planned = [o.split(":", 1)[0] for o in refs(work.get("Out", ""))]
                if path in planned:
                    work["In"] = ";".join(dict.fromkeys([*refs(work["In"]), key]))
        self.event("touch", pace or "-", detail)

    # -- retirement ----------------------------------------------------------
    def _retire(self, selected: set[str], *, cascade: bool, reason: str) -> list[str]:
        """Move rows to the archive, then strip every live reference to them."""
        retired = set(selected)
        if cascade:
            self._cascade(retired)
        for register in REGISTERS:
            keep: list[dict] = []
            for row in self.tables[register]:
                (self.archive[register] if row["ID"] in retired else keep).append(row)
            self.tables[register][:] = keep
        for register in REGISTERS:
            for row in self.tables[register]:
                for field in REF_FIELDS[register]:
                    if (register, field) in HISTORICAL_REFS:
                        continue
                    current = refs(row[field])
                    kept = [c for c in current if c not in retired]
                    if kept != current:
                        row[field] = ";".join(kept)
                        self.changed.add(row["ID"])
        self.changed |= retired
        return sorted(retired)

    def _cascade(self, retired: set[str]) -> None:
        """Take along decisions whose every subject is retired.

        Requirements and assets never cascade: a requirement stands until someone
        retires it by name, and an asset is a fact about the source tree.
        """
        while True:
            added = {
                row["ID"]
                for row in self.tables["decision"]
                if row["ID"] not in retired
                and refs(row["Subject"])
                and set(refs(row["Subject"])) <= retired
            }
            if not added:
                return
            retired |= added
