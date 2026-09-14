"""Approval is durable workflow state, independent of task lifecycle status."""

import pytest
from pacer_mcp.service import Service


def proposal(apply):
    """Create reviewable work without claiming approval."""
    apply(
        {
            "op": "add",
            "register": "todo",
            "row": {
                "ID": "PAC-001",
                "Title": "Proposed work",
                "Phase": "PROPOSAL",
                "DoD": "Exact result",
            },
        }
    )


def admission():
    """Admit an existing proposal without replacing its identity."""
    return {
        "op": "pace",
        "nodule": {
            "ID": "NDL-001",
            "Intent": "Approved work",
            "AbsorptionCriteria": "Exact result",
            "SpawnedPACs": "PAC-001",
        },
        "tasks": [],
    }


def decision(state="APPROVED"):
    """Attest an attributable user decision through the public command lexicon."""
    return {
        "op": "approval",
        "id": "PAC-001",
        "state": state,
        "evidence": "User message: approve the proposed work.",
    }


def test_proposal_is_neither_ready_nor_activatable(project, apply):
    proposal(apply)
    assert project.query("todo", ready=True)["total"] == 0
    for op in [admission(), {"op": "transition", "id": "PAC-001", "status": "DOING"}]:
        with pytest.raises(ValueError, match="approval"):
            apply(op)


def test_approval_admits_existing_id_and_survives_restart(project, apply):
    proposal(apply)
    apply(decision())
    assert project.query("todo", ready=True)["total"] == 1
    apply(admission())
    apply({"op": "transition", "id": "PAC-001", "status": "DOING"})
    row = Service(project.store.root).query(
        "todo",
        fields=[
            "ID",
            "DoD",
            "ApprovalState",
            "ApprovalEvidence",
            "ApprovedAt",
            "ApprovalActor",
            "NDLRefs",
        ],
    )["rows"][0]
    assert row["ID"] == "PAC-001" and row["DoD"] == "Exact result"
    assert row["ApprovalState"] == "APPROVED" and row["ApprovedAt"].endswith("Z")
    assert row["ApprovalEvidence"] == decision()["evidence"] and row["ApprovalActor"] == "tester"
    assert row["NDLRefs"] == "NDL-001"


def test_withdrawal_blocks_activation_and_batch_rolls_back(project, apply):
    proposal(apply)
    apply(decision())
    apply(decision("WITHDRAWN"))
    assert project.query("todo", ready=True)["total"] == 0
    before = project.onboard()["revision"]
    with pytest.raises(ValueError, match="approval"):
        apply({"op": "transition", "id": "PAC-001", "status": "DOING"})
    assert project.onboard()["revision"] == before
    apply(decision())
    before = project.onboard()["revision"]
    with pytest.raises(ValueError, match="TODO"):
        apply({"op": "transition", "id": "PAC-001", "status": "DOING"}, decision("WITHDRAWN"))
    assert project.onboard()["revision"] == before


def test_approval_cannot_be_forged_by_metadata_or_scope_edits(project, apply):
    proposal(apply)
    with pytest.raises(ValueError, match="Protected"):
        apply({"op": "set", "id": "PAC-001", "fields": {"ApprovalState": "APPROVED"}})
    with pytest.raises(ValueError, match="approval"):
        apply({"op": "set", "id": "PAC-001", "fields": {"Phase": "DEVELOPMENT"}}, admission())
    apply(decision())
    with pytest.raises(ValueError, match="approval"):
        apply({"op": "set", "id": "PAC-001", "fields": {"Title": "Different scope"}}, admission())


def test_pending_admission_cannot_bypass_gate_via_reciprocal_link(project, apply):
    proposal(apply)
    apply(
        {
            "op": "pace",
            "nodule": {"ID": "NDL-001", "Intent": "Existing", "AbsorptionCriteria": "Checked"},
            "tasks": [{"ID": "PAC-002", "Title": "Existing", "DoD": "Checked"}],
        }
    )
    with pytest.raises(ValueError, match="approval"):
        apply({"op": "link", "id": "PAC-001", "field": "NDLRefs", "target": "NDL-001"})


def test_migration_does_not_invent_approval_or_acceptance(project, apply):
    proposal(apply)
    state = project.onboard()
    project.migrate(
        actor="tester", revision=state["revision"], onboarding=state["onboarding"], preview=False
    )
    assert project.query("todo", ready=True)["total"] == 0
    assert project.query("todo", fields=["ApprovalState"])["rows"][0]["ApprovalState"] == "PENDING"
    assert project.query("organism")["total"] == 0


def test_pace_accepts_new_task_ids_also_declared_in_spawned_list(project, apply):
    op = admission()
    op["tasks"] = [{"ID": "PAC-001", "Title": "New work", "DoD": "Checked"}]
    apply(op)
    assert project.query("todo")["total"] == 1


@pytest.mark.parametrize("phase", ["PROPOSAL", "DEVELOPMENT"])
def test_split_children_retain_parent_approval_provenance(project, apply, phase):
    proposal(apply)
    apply(decision(), admission())
    apply({"op": "transition", "id": "PAC-001", "status": "DOING"})
    apply(
        {
            "op": "split",
            "id": "PAC-001",
            "children": [
                {
                    "ID": "PAC-001A",
                    "Title": "First part",
                    "DoD": "First narrower check",
                    "Phase": phase,
                },
                {
                    "ID": "PAC-001B",
                    "Title": "Second part",
                    "DoD": "Second narrower check",
                    "Phase": phase,
                },
            ],
        }
    )
    children = [
        r
        for r in project.query("todo", fields=["ID", "ApprovalState", "ApprovalEvidence"])["rows"]
        if r["ID"] != "PAC-001"
    ]
    assert all(
        r["ApprovalState"] == "APPROVED" and "Derived split" in r["ApprovalEvidence"]
        for r in children
    )


def test_proposal_opt_in_cannot_be_cleared_with_phase_metadata(project, apply):
    apply(
        {
            "op": "add",
            "register": "todo",
            "row": {"ID": "PAC-001", "Title": "Legacy", "DoD": "Checked"},
        }
    )
    apply({"op": "set", "id": "PAC-001", "fields": {"Phase": "PROPOSAL"}})
    apply({"op": "set", "id": "PAC-001", "fields": {"Phase": "DEVELOPMENT"}})
    assert project.query("todo", ready=True)["total"] == 0


def test_approval_evidence_and_history_preserve_literal_unknown_ids(project, apply):
    proposal(apply)
    exact = 'User quotation: preserve "PAC-999" literally.\nNo new reference.'
    apply(decision() | {"evidence": exact})
    apply(decision("WITHDRAWN"))
    import json

    history = json.loads(
        project.query("todo", fields=["ApprovalHistory"])["rows"][0]["ApprovalHistory"]
    )
    assert history[-1]["ApprovalEvidence"] == exact


def test_split_cannot_derive_approval_from_invalidated_parent_in_batch(project, apply):
    proposal(apply)
    apply(decision(), admission())
    apply({"op": "transition", "id": "PAC-001", "status": "DOING"})
    before = project.onboard()["revision"]
    with pytest.raises(ValueError, match="approval"):
        apply(
            {"op": "set", "id": "PAC-001", "fields": {"Title": "Changed scope"}},
            {
                "op": "split",
                "id": "PAC-001",
                "children": [
                    {"ID": "PAC-001A", "Title": "A", "DoD": "Narrow A"},
                    {"ID": "PAC-001B", "Title": "B", "DoD": "Narrow B"},
                ],
            },
            decision("WITHDRAWN"),
        )
    assert project.onboard()["revision"] == before
