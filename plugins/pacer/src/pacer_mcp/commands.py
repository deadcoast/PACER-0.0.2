"""The write lexicon: every mutation is an event; registers hold current state only."""

from __future__ import annotations

from pathlib import Path

from pacer_mcp.probe import freshness
from pacer_mcp.schema import (
    HEADERS,
    IMMUTABLE,
    LIMITS,
    NDL_STATUSES,
    OGM_STATUSES,
    PREFIX,
    REF_FIELDS,
    REGISTER_OF,
    REGISTERS,
    TASK_STATUSES,
    empty_row,
    pos_parts,
    refs,
)

DEFAULTS = {
    "todo": {"Status": "TODO"},
    "organism": {"Status": "SCAFFOLD", "Authority": "INFERRED"},
    "overlord": {"Kind": "FILE"},
    "nodule": {"Status": "ACTIVE"},
    "decision": {"Authority": "INFERRED"},
}


class Editor:
    """Apply lexicon operations to in-memory tables and collect ledger events."""

    def __init__(self, tables: dict, actor: str, root: Path):
        self.tables, self.actor, self.root = tables, actor, root
        self.changed: set[str] = set()
        self.events: list[dict] = []

    # -- helpers -------------------------------------------------------------
    def find(self, key: str) -> tuple[str, dict]:
        register = REGISTER_OF.get(key.split("-")[0], "")
        for row in self.tables.get(register, []):
            if row["ID"] == key:
                return register, row
        raise ValueError(f"REFUSAL: Unknown ID {key}")

    def next_id(self, register: str) -> str:
        numbers = [
            int(r["ID"].split("-")[1].rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
            for r in self.tables[register]
        ]
        return f"{PREFIX[register]}-{max([0, *numbers]) + 1:03d}"

    def event(self, op: str, key: str, detail: dict | None = None) -> None:
        self.events.append({"actor": self.actor, "op": op, "id": key, "detail": detail or {}})
        self.changed.add(key)

    def _check_text(self, row: dict) -> None:
        for field, value in row.items():
            if not isinstance(value, str):
                raise ValueError(f"{row.get('ID')}: {field} must be a string")
            if "|" in value or "\n" in value:
                raise ValueError(f"{row.get('ID')}: {field} contains | or newline")
            if field in LIMITS and len(value) > LIMITS[field]:
                raise ValueError(f"{row.get('ID')}: {field} exceeds {LIMITS[field]}")

    def _exists(self, key: str) -> bool:
        return any(r["ID"] == key for reg in REGISTERS for r in self.tables[reg])

    # -- dispatch ------------------------------------------------------------
    def execute(self, op: dict) -> None:
        name = op.get("op")
        handler = getattr(self, f"op_{name}", None)
        if handler is None:
            raise ValueError(f"Unknown operation {name}")
        handler(op)

    def op_add(self, op: dict) -> None:
        register, values = op["register"], dict(op["row"])
        if register not in HEADERS:
            raise ValueError(f"Unknown register {register}")
        key = values.get("ID") or self.next_id(register)
        if self._exists(key):
            raise ValueError(f"Duplicate ID {key}")
        row = empty_row(register, {**values, "ID": key})
        for field, value in DEFAULTS.get(register, {}).items():
            row[field] = row[field] or value
        if register == "decision" and row["Kind"] == "LATCH" and not row["Latched"]:
            row["Latched"] = "false"
        self._check_text(row)
        self.tables[register].append(row)
        self.event("add", key, {"register": register})

    def op_set(self, op: dict) -> None:
        register, row = self.find(op["id"])
        fields = dict(op["fields"])
        blocked = set(fields) & IMMUTABLE
        if blocked:
            raise ValueError(
                f"{op['id']}: {','.join(sorted(blocked))} immutable via set; "
                "use status/move/latch/probe"
            )
        unknown = set(fields) - set(HEADERS[register])
        if unknown:
            raise ValueError(f"{op['id']}: unknown fields {','.join(sorted(unknown))}")
        self._check_text(fields)
        before = {k: row[k] for k in fields}
        row.update(fields)
        self.event("set", op["id"], {"before": before, "after": fields})

    def op_link(self, op: dict) -> None:
        register, row = self.find(op["id"])
        field, target = op["field"], op["target"]
        if field not in REF_FIELDS[register]:
            raise ValueError(f"{op['id']}: {field} is not a reference column")
        if not self._exists(target):
            raise ValueError(f"REFUSAL: Unknown ID {target}")
        current = refs(row[field])
        if op.get("remove"):
            current = [c for c in current if c != target]
        elif target not in current:
            current.append(target)
        row[field] = ";".join(current)
        self.event(
            "unlink" if op.get("remove") else "link",
            op["id"],
            {"field": field, "target": target},
        )

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
        allowed = {"todo": TASK_STATUSES, "organism": OGM_STATUSES, "nodule": NDL_STATUSES}.get(
            register
        )
        if allowed is None or status not in allowed:
            raise ValueError(f"{op['id']}: illegal status {status}")
        if register == "nodule":
            raise ValueError("nodule status changes only through pace/absorb")
        if register == "organism" and status == "VALIDATED_COMPLETE":
            if freshness(row, self.tables, self.root) != "CURRENT":
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
        nodule = dict(op["nodule"])
        tasks = [dict(t) for t in op.get("tasks", [])]
        requirements = [dict(r) for r in op.get("requirements", [])]
        decisions = [dict(d) for d in op.get("decisions", [])]
        for row in requirements:
            self.op_add({"op": "add", "register": "organism", "row": row})
        for row in decisions:
            self.op_add({"op": "add", "register": "decision", "row": row})
        for row in tasks:
            self.op_add({"op": "add", "register": "todo", "row": row})
        spawned = [t["ID"] for t in tasks if t.get("Kind", "PACE") == "PACE"]
        spawned += refs(nodule.get("Spawned", ""))
        nodule["Spawned"] = ";".join(dict.fromkeys(spawned))
        targets = [r["ID"] for r in requirements] + refs(nodule.get("Targets", ""))
        nodule["Targets"] = ";".join(dict.fromkeys(targets))
        nodule["Status"] = "ACTIVE"
        self.op_add({"op": "add", "register": "nodule", "row": nodule})

    def op_absorb(self, op: dict) -> None:
        register, row = self.find(op["id"])
        if register != "nodule" or row["Status"] != "ACTIVE":
            raise ValueError(f"{op['id']}: only an ACTIVE nodule can be absorbed")
        errors = []
        for key in refs(row.get("Spawned", "")):
            if self.find(key)[1].get("Status") != "DONE":
                errors.append(f"{key} not DONE")
        for key in refs(row.get("Targets", "")):
            target = self.find(key)[1]
            if (
                target.get("Status") != "VALIDATED_COMPLETE"
                or freshness(target, self.tables, self.root) != "CURRENT"
            ):
                errors.append(f"{key} incomplete or stale")
        for item in refs(row.get("Out", "")):
            path = item.split(":", 1)[0]
            if not any(r["Path"] == path for r in self.tables["overlord"]):
                errors.append(f"{item} unregistered")
        if errors:
            raise ValueError(f"{op['id']}: incomplete: " + "; ".join(errors))
        row["Status"] = "ABSORBED"
        self.event("absorb", op["id"], {})

    def op_touch(self, op: dict) -> None:
        path = op["path"]
        pace = op.get("pace", "")
        registered = any(r["Path"] == path for r in self.tables["overlord"])
        detail: dict = {"path": path, "registered": registered}
        if not registered:
            key = self.next_id("overlord")
            self.op_add(
                {
                    "op": "add",
                    "register": "overlord",
                    "row": {"ID": key, "Path": path, "Kind": "FILE", "Tags": "#unpurposed"},
                }
            )
            detail["new"] = key
            if pace:
                _, row = self.find(pace)
                outs = [o.split(":", 1)[0] for o in refs(row.get("Out", ""))]
                if path in outs:
                    row["In"] = ";".join(dict.fromkeys(refs(row["In"]) + [key]))
        self.event("touch", pace or path, detail)
