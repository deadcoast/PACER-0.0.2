"""The single PACER mutation lexicon, independent of CLI and MCP transport."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pacer_mcp.context import context_snapshot, operational_nodules, required_closure
from pacer_mcp.evidence import evaluate_rule, stale_requirements
from pacer_mcp.schema import (
    HISTORY,
    OGM_STATUSES,
    PAIRS,
    REF_FIELDS,
    TODO_TRANSITIONS,
    empty_row,
    hard_blockers,
    refs,
    utc_now,
)
from pacer_mcp.semantics import (
    MEANING_FIELDS,
    NEXT_ACTIONS,
    approval_allowed,
    approval_basis,
    approval_state,
    canonical,
)
from pacer_mcp.validation import absorption_errors


class Editor:
    """Apply commands to an isolated candidate; publication belongs to Store."""

    def __init__(
        self, tables: dict, actor: str, root: Path | None = None, *, legacy_migration: bool = False
    ):
        self.tables = tables
        self.actor = actor
        self.now = utc_now()
        self.changed: set[str] = set()
        self.root = root
        self.legacy_migration = legacy_migration

    def find(self, row_id: str) -> tuple[str, dict[str, str]]:
        """Locate one immutable row identity across all four organs."""
        for register, rows in self.tables.items():
            for row in rows:
                if row["ID"] == row_id:
                    return register, row
        raise ValueError(f"REFUSAL: Unknown ID {row_id}")

    def note(self, row: dict, text: str) -> None:
        """Append dated actor history and update the row's modification time."""
        entry = f"{self.now} {self.actor}: {text}"
        row["Notes"] = (row.get("Notes", "") + " | " + entry).strip(" |")
        if "UpdatedAt" in row:
            row["UpdatedAt"] = self.now
        self.changed.add(row["ID"])

    def execute(self, operation: dict) -> None:
        """Dispatch only declared operations; unknown fields fail visibly."""
        allowed = {
            "add": {"op", "register", "row"},
            "set": {"op", "id", "fields"},
            "append": {"op", "id", "field", "text"},
            "link": {"op", "id", "field", "target", "remove"},
            "transition": {"op", "id", "status", "evidence"},
            "pace": {"op", "nodule", "tasks", "requirements"},
            "split": {"op", "id", "children"},
            "absorb": {"op", "id", "evidence"},
            "verify": {"op", "id", "evidence", "artifact"},
            "checkpoint": {"op", "id", "next_action"},
            "refresh": {"op", "id"},
            "approval": {"op", "id", "state", "evidence"},
        }
        name = operation.get("op")
        if name not in allowed or set(operation) - allowed[name]:
            raise ValueError(f"Unknown operation or fields: {name}")
        if name == "add":
            if operation["register"] not in {"todo", "overlord"}:
                raise ValueError("New design requirements and nodules enter through pace")
            self.add(operation["register"], operation["row"])
        elif name == "pace":
            self.pace(operation["nodule"], operation["tasks"], operation.get("requirements", []))
        elif name == "split":
            self.split(operation["id"], operation["children"])
        else:
            register, row = self.find(operation["id"])
            if register == "nodule" and row["Status"] == "ABSORBED":
                raise ValueError("Absorbed nodules are immutable history")
            if name == "set":
                self.set_fields(register, row, operation["fields"])
            elif name == "approval":
                self.approval(register, row, operation["state"], operation["evidence"])
            elif name == "append":
                field = operation["field"]
                if field not in HISTORY or field not in row or not operation["text"].strip():
                    raise ValueError("append needs a nonempty existing history field")
                row[field] = (row[field] + " | " + operation["text"].strip()).strip(" |")
                self.note(row, f"appended {field}")
            elif name == "link":
                field = operation["field"]
                if field not in REF_FIELDS[register]:
                    raise ValueError(f"Not a typed reference column: {field}")
                self.find(operation["target"])
                targets = refs(row[field])
                if operation.get("remove", False):
                    targets = [r for r in targets if r != operation["target"]]
                elif operation["target"] not in targets:
                    targets.append(operation["target"])
                self.set_fields(register, row, {field: ";".join(targets)})
            elif name == "transition":
                self.transition(register, row, operation["status"], operation.get("evidence", ""))
            elif name == "absorb":
                self.absorb(register, row, operation.get("evidence", ""))
            elif name == "verify":
                self.verify(
                    register, row, operation.get("evidence", ""), operation.get("artifact", "")
                )
            elif name == "checkpoint":
                if register != "todo" or operation["next_action"] not in NEXT_ACTIONS:
                    raise ValueError("checkpoint needs a task and defined next_action")
                row["NextAction"] = operation["next_action"]
                row["ContextCheckpoint"] = canonical(
                    context_snapshot(self.tables, self.root, row["ID"])
                )
                self.note(row, "checkpoint; next action " + row["NextAction"])
            elif name == "refresh":
                self.refresh(row)

    def add(self, register: str, values: dict) -> dict:
        """Add a new row without allowing forged completion or timestamps."""
        row = empty_row(register, values)
        if not row["ID"]:
            raise ValueError("ID required")
        if any(r["ID"] == row["ID"] for rows in self.tables.values() for r in rows):
            raise ValueError(f"Duplicate ID {row['ID']}")
        for field in (
            "StartedAt",
            "DoneAt",
            "AbsorbedAt",
            "EvidenceBindings",
            "EvidenceArtifact",
            "EvidenceFor",
            "ContextCheckpoint",
            "ApprovalEvidence",
            "ApprovalActor",
            "ApprovedAt",
            "ApprovalBasis",
            "ApprovalHistory",
        ):
            if row.get(field):
                raise ValueError(f"Workflow owns {field}")
        if register == "todo":
            if row.get("ApprovalState") not in {"", "LEGACY", "PENDING"}:
                raise ValueError("New task approval requires the approval command")
            row["ApprovalState"] = approval_state(row)
            if row["Status"] not in {"", "TODO"}:
                raise ValueError(f"REFUSAL: Illegal transition TODO->{row['Status']}")
            row["Status"] = "TODO"
        if register == "organism":
            row["Status"] = row["Status"] or "SCAFFOLD"
            if row["Status"] not in {"SCAFFOLD", "PACED_REQUIREMENT"}:
                raise ValueError("New requirements must be incomplete before verification")
            if row["AcceptanceEvidence"] or row["AbsorbedFromNDL"]:
                raise ValueError("Pacing cannot forge acceptance or absorption history")
        self.tables[register].append(row)
        self.note(row, f"added {register} row")
        self.reconcile(allow_forward=True)
        return row

    def _guard_inverse_basis(self, register: str, row: dict, field: str) -> None:
        if field in {"EvidenceArtifact", "EvidenceFor"}:
            raise ValueError("Protected evidence relation; use verify")
        if register == "organism" and field == "OVRRefs" and row["Status"] == "VALIDATED_COMPLETE":
            if (
                self.legacy_migration
                and not row.get("RuleType")
                and not row.get("EvidenceBindings")
            ):
                return
            raise ValueError("Demote a validated requirement before changing its meaning or basis")

    def set_fields(self, register: str, row: dict, fields: dict) -> None:
        """Update metadata and remove reciprocal links when a typed edge is removed."""
        protected = HISTORY | {
            "ID",
            "Status",
            "StartedAt",
            "DoneAt",
            "CreatedAt",
            "AbsorbedAt",
            "UpdatedAt",
            "DoD",
            "AcceptanceEvidence",
            "AbsorbedFromNDL",
            "EvidenceBindings",
            "EvidenceArtifact",
            "EvidenceFor",
            "ContextCheckpoint",
            "NextAction",
            "ApprovalState",
            "ApprovalEvidence",
            "ApprovalActor",
            "ApprovedAt",
            "ApprovalBasis",
            "ApprovalHistory",
        }
        if register == "nodule":
            protected |= {"Intent", "AbsorptionCriteria", "Lane", "NoduleName"}
            if row.get("ContextPolicy") == "REQUIRED":
                protected |= {"ContextPolicy", "UserRequest"}
        if set(fields) & protected:
            raise ValueError("Protected field; use lifecycle or append commands")
        if any(k not in row or not isinstance(v, str) for k, v in fields.items()):
            raise ValueError("set requires existing columns with string values")
        if (
            register == "organism"
            and row["Status"] == "VALIDATED_COMPLETE"
            and any(row[k] != value for k, value in fields.items() if k in MEANING_FIELDS)
        ):
            raise ValueError("Demote a validated requirement before changing its meaning or basis")
        for field, value in fields.items():
            if (
                register == "todo"
                and field == "Phase"
                and value == "PROPOSAL"
                and approval_state(row) == "LEGACY"
            ):
                row["ApprovalState"] = "PENDING"
            admitted_scope = (
                register == "nodule"
                and field in {"NewAssets", "TargetOVR", "OGMTargets", "SpawnedPACs"}
            ) or field == "NDLRefs"
            if admitted_scope and set(refs(row[field])) - set(refs(value)):
                raise ValueError("Cannot remove admitted nodule scope")
            for a, f, b, g in PAIRS + [(b, g, a, f) for a, f, b, g in PAIRS]:
                if register == a and field == f:
                    for removed in set(refs(row[field])) - set(refs(value)):
                        _, target = self.find(removed)
                        if b == "nodule" and target["Status"] == "ABSORBED":
                            raise ValueError("Cannot unlink absorbed history")
                        self._guard_inverse_basis(b, target, g)
                        target[g] = ";".join(r for r in refs(target[g]) if r != row["ID"])
                        self.note(target, f"removed reciprocal {g} edge from {row['ID']}")
            row[field] = value
            # Publish each edge to both endpoints inside the candidate immediately.
            for a, f, b, g in PAIRS + [(b, g, a, f) for a, f, b, g in PAIRS]:
                if register == a and field == f:
                    for added in refs(value):
                        target = next((r for r in self.tables[b] if r["ID"] == added), None)
                        if target is not None and row["ID"] not in refs(target[g]):
                            if b == "nodule" and target["Status"] == "ABSORBED":
                                raise ValueError("Cannot add scope to absorbed history")
                            self._guard_inverse_basis(b, target, g)
                            target[g] = ";".join(refs(target[g]) + [row["ID"]])
                            self.note(target, f"linked {g} to {row['ID']}")
        self.note(row, "updated " + ";".join(fields))

    def reconcile(self, *, allow_forward: bool = False) -> None:
        """Add reciprocal typed edges; removal is explicit in set_fields."""
        for a, f, b, g in PAIRS:
            for left, field, right, back in ((a, f, b, g), (b, g, a, f)):
                for row in self.tables[left]:
                    for target_id in refs(row.get(field, "")):
                        if allow_forward and not any(
                            r["ID"] == target_id for rows in self.tables.values() for r in rows
                        ):
                            continue
                        actual, target = self.find(target_id)
                        if actual != right:
                            raise ValueError(f"Wrong reference type: {row['ID']}.{field}")
                        existing = refs(target.get(back, ""))
                        if row["ID"] not in existing:
                            if right == "nodule" and target["Status"] == "ABSORBED":
                                raise ValueError("Cannot add new scope to absorbed history")
                            self._guard_inverse_basis(right, target, back)
                            target[back] = ";".join(existing + [row["ID"]])
                            self.note(target, f"linked {back} to {row['ID']}")

    def transition(
        self, register: str, row: dict, status: str, evidence: str, *, verified: bool = False
    ) -> None:
        """Enforce state transitions, hard dependency gates and truthful evidence."""
        old = row.get("Status", "")
        if register == "todo":
            if (old, status) not in TODO_TRANSITIONS:
                raise ValueError(f"REFUSAL: Illegal transition {old}->{status}")
            if status != "TODO" and not approval_allowed(row):
                raise ValueError("Task approval required before activation or advancement")
            if old == "DOING":
                start = datetime.fromisoformat(row["StartedAt"].replace("Z", "+00:00"))
                if datetime.now(UTC) - start > timedelta(hours=48):
                    raise ValueError(
                        "DOING exceeds 48h; split into narrower tasks before advancing"
                    )
            if status == "DONE":
                blocked = [r for r in hard_blockers(row) if self.find(r)[1]["Status"] != "DONE"]
                if blocked:
                    raise ValueError(f"REFUSAL: Blocked by {';'.join(blocked)}")
                if not evidence.strip():
                    raise ValueError("REFUSAL: Evidence required")
                index = {r["ID"]: r for rows in self.tables.values() for r in rows}
                if operational_nodules(row, index):
                    for key in refs(row["OGMRefs"]):
                        requirement = index[key]
                        if (
                            requirement["Status"] != "VALIDATED_COMPLETE"
                            or evaluate_rule(requirement, index, self.root)["freshness"]
                            != "CURRENT"
                        ):
                            raise ValueError(f"Task requires current verified rule {key}")
                row["DoneAt"] = self.now
            if status == "DOING":
                row["Assignee"] = row["Assignee"] or self.actor
                row["StartedAt"] = self.now
        elif register == "organism":
            if status not in OGM_STATUSES or old == status:
                raise ValueError(f"REFUSAL: Illegal transition {old}->{status}")
            if (
                status == "VALIDATED_COMPLETE" or old == "VALIDATED_COMPLETE"
            ) and not evidence.strip():
                raise ValueError("REFUSAL: Evidence required")
            if status == "VALIDATED_COMPLETE":
                index = {r["ID"]: r for rows in self.tables.values() for r in rows}
                if (row.get("RuleType") or operational_nodules(row, index)) and not verified:
                    raise ValueError("Operational acceptance requires verify")
                for target in refs(row["BlockedByOGM"]):
                    if self.find(target)[1]["Status"] != "VALIDATED_COMPLETE":
                        raise ValueError(f"Requirement blocked by {target}")
                row["AcceptanceEvidence"] = evidence
            else:
                # The previous acceptance remains in Notes; current evidence clears on regression.
                if row["AcceptanceEvidence"]:
                    self.note(row, "previous acceptance: " + row["AcceptanceEvidence"])
                row["AcceptanceEvidence"] = ""
        else:
            raise ValueError("Use pace/absorb for nodule state")
        row["Status"] = status
        self.note(row, f"{old}->{status}" + (f"; evidence: {evidence}" if evidence else ""))

    def verify(self, register: str, row: dict, evidence: str, artifact: str) -> None:
        """Accept a passing rule using source fingerprints produced by the runtime."""
        if register != "organism" or self.root is None or not evidence.strip():
            raise ValueError("verify requires a requirement, project root and evidence description")
        index = {r["ID"]: r for rows in self.tables.values() for r in rows}
        observation = evaluate_rule(row, index, self.root, artifact)
        if observation["result"] != "PASS":
            raise ValueError(
                f"Cannot verify rule {row['ID']}: {observation['result']} {observation['reason']}"
            )
        for target in refs(row["BlockedByOGM"]):
            if (
                index[target]["Status"] != "VALIDATED_COMPLETE"
                or evaluate_rule(index[target], index, self.root)["freshness"] != "CURRENT"
            ):
                raise ValueError(f"Rule dependency requires current verification: {target}")
        if row.get("EvidenceBindings"):
            self.note(row, "previous binding: " + row["EvidenceBindings"])
        old_artifact = row.get("EvidenceArtifact", "")
        new_artifact = artifact or old_artifact
        if row.get("RuleType") != "manual" and new_artifact:
            raise ValueError("Automatic rules do not accept manual artifacts")
        if old_artifact != new_artifact:
            if old_artifact:
                previous = index[old_artifact]
                previous["EvidenceFor"] = ";".join(
                    v for v in refs(previous.get("EvidenceFor", "")) if v != row["ID"]
                )
                self.note(previous, "superseded evidence for " + row["ID"])
            if new_artifact:
                target = index[new_artifact]
                target["EvidenceFor"] = ";".join(
                    dict.fromkeys(refs(target.get("EvidenceFor", "")) + [row["ID"]])
                )
                self.note(target, "evidence for " + row["ID"])
            row["EvidenceArtifact"] = new_artifact
        row["EvidenceBindings"] = canonical(observation["basis"])
        if row["Status"] != "VALIDATED_COMPLETE":
            self.transition(register, row, "VALIDATED_COMPLETE", evidence, verified=True)
        else:
            row["AcceptanceEvidence"] = evidence
            self.note(row, "reverified against current source; " + evidence)

    def refresh(self, task: dict) -> None:
        """Record stale acceptance and demote demonstrated failures plus their dependents."""
        if not task["ID"].startswith("PAC-") or self.root is None:
            raise ValueError("refresh requires a task and project root")
        index = {r["ID"]: r for rows in self.tables.values() for r in rows}
        required, _ = required_closure(self.tables, task["ID"])
        stale = [key for key in stale_requirements(self.tables, self.root) if key in required]
        failed = {
            key for key in stale if evaluate_rule(index[key], index, self.root)["result"] == "FAIL"
        }
        while True:
            more = {key for key in stale if set(refs(index[key]["BlockedByOGM"])) & failed}
            if more <= failed:
                break
            failed |= more
        for key in stale:
            row = index[key]
            if key in failed:
                status = (
                    "PACED_REQUIREMENT"
                    if any(row.get(f) for f in ("PACRefs", "OVRRefs", "BlockedByOGM"))
                    else "SCAFFOLD"
                )
                self.transition(
                    "organism",
                    row,
                    status,
                    f"Rule regression detected under {task['ID']}; prior source binding retained",
                )
            else:
                self.note(
                    row,
                    f"stale evidence under {task['ID']}; reverify passing or unresolved rule",
                )

    def pace(self, nodule: dict, tasks: list[dict], requirements: list[dict]) -> None:
        """Create one growth lane and its tasks and provisional design targets together."""
        if not tasks and not refs(nodule.get("SpawnedPACs", "")):
            raise ValueError("ACTIVE nodule needs at least one spawned PAC")
        new_ids = {task.get("ID") for task in tasks}
        for key in refs(nodule.get("SpawnedPACs", "")):
            if key in new_ids:
                continue
            register, task = self.find(key)
            if register != "todo" or task["Status"] != "TODO" or not approval_allowed(task):
                raise ValueError("Existing task admission requires TODO and current approval")
        if nodule.get("Status", "ACTIVE") != "ACTIVE":
            raise ValueError("New nodule must be ACTIVE")
        row = self.add("nodule", nodule | {"Status": "ACTIVE", "CreatedAt": self.now})
        row["Lane"] = row["Lane"] or "main"
        ogm_ids = refs(row["OGMTargets"])
        for values in requirements:
            target = self.add("organism", values)
            target["NDLRefs"] = ";".join(dict.fromkeys(refs(target["NDLRefs"]) + [row["ID"]]))
            ogm_ids.append(target["ID"])
        row["OGMTargets"] = ";".join(dict.fromkeys(ogm_ids))
        spawned = refs(row["SpawnedPACs"])
        for values in tasks:
            task = self.add("todo", values)
            task["NDLRefs"] = ";".join(dict.fromkeys(refs(task["NDLRefs"]) + [row["ID"]]))
            task["OGMRefs"] = task["OGMRefs"] or row["OGMTargets"]
            spawned.append(task["ID"])
        row["SpawnedPACs"] = ";".join(dict.fromkeys(spawned))
        self.reconcile()

    def approval(self, register: str, row: dict, state: str, evidence: str) -> None:
        """Record attributable approval or withdrawal without changing task lifecycle."""
        if register != "todo" or row["Status"] != "TODO":
            raise ValueError("approval requires a TODO task; return active work to TODO first")
        if state not in {"APPROVED", "WITHDRAWN"} or not evidence.strip():
            raise ValueError("approval requires APPROVED/WITHDRAWN and nonempty evidence")
        history = json.loads(row.get("ApprovalHistory") or "[]")
        history.append(
            {
                k: row.get(k, "")
                for k in (
                    "ApprovalState",
                    "ApprovalEvidence",
                    "ApprovalActor",
                    "ApprovedAt",
                    "ApprovalBasis",
                )
            }
        )
        row["ApprovalHistory"] = canonical(history)
        row["ApprovalState"] = state
        row["ApprovalEvidence"] = evidence
        row["ApprovalActor"] = self.actor
        row["ApprovedAt"] = self.now if state == "APPROVED" else ""
        row["ApprovalBasis"] = approval_basis(row) if state == "APPROVED" else ""
        self.note(row, "approval decision " + state + "; evidence and previous decisions retained")

    def split(self, row_id: str, children: list[dict]) -> None:
        """Preserve the parent's scope and DoD, add child work and block the parent on it."""
        register, parent = self.find(row_id)
        if register != "todo" or parent["Status"] != "DOING" or len(children) < 2:
            raise ValueError("split requires a DOING task and at least two narrower children")
        if not approval_allowed(parent):
            raise ValueError("Current parent approval required before deriving split work")
        # Splitting is the only exit for stale work; the original DoD survives.
        parent["Status"] = "TODO"
        self.note(parent, "DOING->TODO; split into narrower work")
        blockers = refs(parent["BlockedBy"])
        types = refs(parent["DependencyType"]) or ["hard"]
        if len(types) == 1:
            types *= len(blockers)
        for values in children:
            if not values.get("ID", "").startswith(row_id) or values["ID"] == row_id:
                raise ValueError("Split children must suffix the parent ID")
            if not values.get("DoD") or values["DoD"] == parent["DoD"]:
                raise ValueError("Split child requires its own narrower DoD")
            inherited = {
                k: parent[k]
                for k in ("Phase", "Priority", "Assignee", "OGMRefs", "OVRRefs", "NDLRefs", "Tags")
            }
            child_values = inherited | values
            if set(refs(parent["NDLRefs"])) - set(refs(child_values["NDLRefs"])):
                raise ValueError("Cannot remove admitted nodule scope from split children")
            child = self.add("todo", child_values)
            if approval_state(parent) == "APPROVED":
                self.approval(
                    "todo",
                    child,
                    "APPROVED",
                    "Derived split within approved "
                    + parent["ID"]
                    + ": "
                    + parent["ApprovalEvidence"],
                )
            blockers.append(child["ID"])
            types.append("hard")
        parent["BlockedBy"], parent["DependencyType"] = ";".join(blockers), ";".join(types)
        self.note(parent, "split; parent DoD preserved")

    def absorb(self, register: str, row: dict, evidence: str) -> None:
        """Verify the whole scope before moving its sole canonical row to archive."""
        if register != "nodule" or row["Status"] != "ACTIVE":
            raise ValueError("absorb requires an ACTIVE nodule")
        if not evidence.strip():
            raise ValueError("REFUSAL: Evidence required")
        self.reconcile()
        errors = absorption_errors(row, self.tables)
        if errors:
            raise ValueError(errors[0])
        if row.get("ContextPolicy") == "REQUIRED":
            index = {r["ID"]: r for rows in self.tables.values() for r in rows}
            for key in refs(row["OGMTargets"]):
                if evaluate_rule(index[key], index, self.root)["freshness"] != "CURRENT":
                    raise ValueError(f"Absorption requires current verified rule {key}")
        row["Status"] = "ABSORBED"
        row["AbsorbedAt"] = self.now
        row["AcceptanceEvidence"] = evidence
        for target_id in refs(row["OGMTargets"]):
            _, target = self.find(target_id)
            target["AbsorbedFromNDL"] = ";".join(
                dict.fromkeys(refs(target["AbsorbedFromNDL"]) + [row["ID"]])
            )
            self.note(target, "absorbed from " + row["ID"])
        self.note(row, "ACTIVE->ABSORBED; evidence: " + evidence)
