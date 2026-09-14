"""Task context must be sufficient, current and recoverable across processes."""

import json

import pytest
from pacer_mcp.service import Service


def test_context_contains_required_meaning_without_unrelated_history(operational):
    packet = operational.context("PAC-001")
    assert packet["complete"]
    assert {"PAC-001", "OGM-001", "NDL-001", "OVR-007"} <= set(packet["required_ids"])
    assert "OVR-008" not in packet["required_ids"]
    assert packet["tables"]["organism"]["columns"].count("Authority") == 1
    assert packet["rules"][0]["result"] == "PASS"
    assert packet["rules"][0]["freshness"] == "UNBOUND"
    assert packet["receipt"]["task"] == "PAC-001"


def test_budget_refuses_to_drop_mandatory_context(operational):
    packet = operational.context("PAC-001", max_bytes=512)
    assert not packet["complete"]
    assert packet["receipt"] is None and packet["required_bytes"] > 512
    assert packet["tables"] == {}
    assert "context_budget" in {d["code"] for d in packet["diagnostics"]}


def test_operational_writes_require_current_context(operational):
    r = operational.onboard()
    with pytest.raises(ValueError, match="context"):
        operational.apply(
            [{"op": "transition", "id": "PAC-001", "status": "DOING"}],
            actor="tester",
            revision=r["revision"],
            onboarding=r["onboarding"],
        )


def test_source_drift_invalidates_context_even_when_register_revision_is_unchanged(operational):
    r = operational.onboard()
    packet = operational.context("PAC-001")
    (operational.store.root / "settings.json").write_text('{"retries":5}', encoding="utf-8")
    with pytest.raises(ValueError, match="Stale context"):
        operational.apply(
            [{"op": "transition", "id": "PAC-001", "status": "DOING"}],
            actor="tester",
            revision=r["revision"],
            onboarding=r["onboarding"],
            context=packet["receipt"],
        )


def test_checkpoint_cold_resume_reports_source_delta(operational, operate):
    operate({"op": "checkpoint", "id": "PAC-001", "next_action": "verify"})
    saved = json.loads(
        operational.query("todo", fields=["ContextCheckpoint"])["rows"][0]["ContextCheckpoint"]
    )
    assert saved["task"] == "PAC-001"
    (operational.store.root / "settings.json").write_text('{"retries":1}', encoding="utf-8")
    cold = Service(operational.store.root).context("PAC-001")
    assert cold["next_action"] == "verify"
    assert cold["delta"]["changed_sources"] == ["settings.json"]
    assert cold["rules"][0]["result"] == "FAIL"


def test_context_closes_deep_hard_dependencies(paced, apply):
    operations = []
    for number in range(3, 9):
        operations.append(
            {
                "op": "add",
                "register": "todo",
                "row": {
                    "ID": f"PAC-{number:03d}",
                    "Title": "Dependency",
                    "DoD": "checked",
                    "BlockedBy": f"PAC-{number - 1:03d}",
                    "DependencyType": "hard",
                },
            }
        )
    apply(*operations)
    assert {f"PAC-{n:03d}" for n in range(1, 9)} <= set(paced.context("PAC-008")["required_ids"])


def test_context_keeps_operative_instructions(operational, operate):
    operate(
        {
            "op": "set",
            "id": "PAC-001",
            "fields": {
                "Instructions": "Preserve leading whitespace exactly.",
                "ValidationCriteria": "Compare exact bytes.",
                "Context": "External whitespace consumer.",
                "ExpectedOutput": "Exact file bytes.",
                "ErrorHandling": "Retain partial evidence.",
                "DependencyReason": "Consumer contract.",
                "UnblockingStrategy": "Inspect consumer.",
            },
        }
    )
    packet = operational.context("PAC-001")
    assert packet["complete"]
    encoded = json.dumps(packet)
    for text in (
        "Preserve leading whitespace exactly.",
        "Compare exact bytes.",
        "External whitespace consumer.",
        "Rule verified against source",
        "Keep retries bounded",
        "Exact file bytes.",
        "Retain partial evidence.",
        "Consumer contract.",
        "Inspect consumer.",
    ):
        assert text in encoded


def test_reciprocal_admission_requires_context(operational, apply):
    before = operational.onboard()["revision"]
    with pytest.raises(ValueError, match="context"):
        apply({"op": "set", "id": "OVR-008", "fields": {"NDLRefs": "NDL-001"}})
    assert operational.onboard()["revision"] == before


def test_pace_requires_a_context_retrieval_before_operational_work(project, apply):
    with pytest.raises(ValueError, match="context"):
        apply(
            {
                "op": "pace",
                "nodule": {
                    "ID": "NDL-001",
                    "NoduleName": "test",
                    "Lane": "main",
                    "Intent": "Read authority",
                    "UserRequest": "Read the README.",
                    "ContextPolicy": "REQUIRED",
                    "TargetOVR": "OVR-001",
                    "AbsorptionCriteria": "Read authority",
                },
                "tasks": [{"ID": "PAC-001", "Title": "Read", "DoD": "Read", "OVRRefs": "OVR-001"}],
            },
            {"op": "transition", "id": "PAC-001", "status": "DOING"},
        )
    assert project.query("nodule")["rows"] == []


def test_nodule_target_seeds_reverse_impact_without_task_asset_refs(operational, operate):
    operate(
        {"op": "set", "id": "OVR-008", "fields": {"Requires": "OVR-007"}},
        {"op": "set", "id": "PAC-001", "fields": {"OVRRefs": ""}},
    )
    packet = operational.context("PAC-001")
    assert "OVR-008" in packet["required_ids"] and "OVR-008" in packet["impacted"]


def test_existing_scope_adopts_context_policy_with_a_current_receipt(paced, apply):
    apply(
        {
            "op": "set",
            "id": "NDL-001",
            "fields": {
                "UserRequest": "Deliver a verified requirement.",
                "ContextPolicy": "REQUIRED",
            },
        },
        context=paced.context("PAC-001")["receipt"],
    )
    assert paced.query("nodule", fields=["ContextPolicy"])["rows"][0]["ContextPolicy"] == "REQUIRED"
    with pytest.raises(ValueError, match="context"):
        apply({"op": "transition", "id": "PAC-001", "status": "DOING"})


def test_next_nodule_can_maintain_assets_from_absorbed_scope(operational, operate, apply):
    operate(
        {"op": "verify", "id": "OGM-001", "evidence": "Observed"},
        {"op": "transition", "id": "PAC-001", "status": "DOING"},
        {"op": "transition", "id": "PAC-001", "status": "REVIEW"},
        {"op": "transition", "id": "PAC-001", "status": "DONE", "evidence": "Checked"},
        {"op": "absorb", "id": "NDL-001", "evidence": "Checked"},
    )
    apply(
        {
            "op": "pace",
            "nodule": {
                "ID": "NDL-002",
                "NoduleName": "next",
                "Lane": "main",
                "Intent": "Maintain existing settings",
                "ContextPolicy": "REQUIRED",
                "UserRequest": "Maintain settings.",
                "TargetOVR": "OVR-007",
                "OGMTargets": "OGM-001",
                "AbsorptionCriteria": "Current settings verified",
            },
            "tasks": [
                {
                    "ID": "PAC-002",
                    "Title": "Maintain",
                    "DoD": "Current settings verified",
                    "OVRRefs": "OVR-007",
                    "OGMRefs": "OGM-001",
                }
            ],
        }
    )
    apply(
        {"op": "set", "id": "OVR-007", "fields": {"Exports": "retries"}},
        context=operational.context("PAC-002")["receipt"],
    )
    assert operational.evaluate("OGM-001")["freshness"] == "STALE"
    assert operational.query("nodule", where={"ID": "NDL-001"})["rows"][0]["Status"] == "ABSORBED"
