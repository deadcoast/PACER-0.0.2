"""Acceptance binds rule meaning and source, and survives honest regression."""

import hashlib
import json

import pytest


def test_rule_verification_binds_source_and_detects_drift(operational, operate):
    operate({"op": "verify", "id": "OGM-001", "evidence": "Runtime bound checked"})
    assert operational.evaluate("OGM-001")["freshness"] == "CURRENT"
    (operational.store.root / "settings.json").write_text('{"retries":1}', encoding="utf-8")
    assert operational.evaluate("OGM-001")["freshness"] == "STALE"
    assert operational.evaluate("OGM-001")["result"] == "FAIL"
    operate({"op": "refresh", "id": "PAC-001"})
    row = operational.query("organism", fields=["Status", "AcceptanceEvidence", "Notes"])["rows"][0]
    assert row["Status"] != "VALIDATED_COMPLETE" and row["AcceptanceEvidence"] == ""
    assert "previous acceptance" in row["Notes"]


def test_plain_evidence_cannot_bypass_operational_verification(operational, operate):
    with pytest.raises(ValueError, match="verify"):
        operate(
            {
                "op": "transition",
                "id": "OGM-001",
                "status": "VALIDATED_COMPLETE",
                "evidence": "trust me",
            }
        )


@pytest.mark.parametrize("value", [1, True, "3"])
def test_numeric_rule_does_not_coerce_invalid_values(operational, operate, value):
    (operational.store.root / "settings.json").write_text(
        json.dumps({"retries": value}), encoding="utf-8"
    )
    before = operational.onboard()["revision"]
    with pytest.raises(ValueError, match="rule"):
        operate({"op": "verify", "id": "OGM-001", "evidence": "must fail"})
    assert operational.onboard()["revision"] == before


def test_manual_report_requires_matching_meaning_and_sources(operational, operate):
    operate(
        {
            "op": "set",
            "id": "OGM-001",
            "fields": {
                "RuleType": "manual",
                "RuleSubject": "",
                "RuleSelector": "",
                "RuleValue": "",
            },
        }
    )
    observation = operational.evaluate("OGM-001")
    report = operational.store.root / "verification.json"
    report.write_text(
        json.dumps(
            {
                "requirement": "OGM-001",
                "meaning": observation["meaning"],
                "sources": observation["sources"],
                "result": "PASS",
                "command": ["python", "check_settings.py"],
            }
        ),
        encoding="utf-8",
    )
    operate(
        {
            "op": "add",
            "register": "overlord",
            "row": {
                "ID": "OVR-009",
                "AssetType": "FILE",
                "Path": "verification.json",
                "Purpose": "Test result",
                "NDLRefs": "NDL-001",
                "PACRefs": "PAC-001",
            },
        }
    )
    operate({"op": "verify", "id": "OGM-001", "artifact": "OVR-009", "evidence": "Test report"})
    assert operational.evaluate("OGM-001")["freshness"] == "CURRENT"
    payload = json.loads(report.read_text())
    payload["result"] = "FAIL"
    report.write_text(json.dumps(payload), encoding="utf-8")
    assert operational.evaluate("OGM-001")["freshness"] == "STALE"


def test_evidence_bindings_cannot_be_forged_or_erased(operational, operate):
    with pytest.raises(ValueError, match="Protected"):
        operate({"op": "set", "id": "OGM-001", "fields": {"EvidenceBindings": "{}"}})
    operate({"op": "verify", "id": "OGM-001", "evidence": "checked"})
    with pytest.raises(ValueError, match="Demote"):
        operate({"op": "set", "id": "OGM-001", "fields": {"RuleValue": "1"}})


def test_file_digest_rule_preserves_exact_bytes(operational, operate):
    original = (operational.store.root / "settings.json").read_bytes()
    operate(
        {
            "op": "set",
            "id": "OGM-001",
            "fields": {
                "RuleType": "file_sha256",
                "RuleSelector": "",
                "RuleValue": json.dumps(hashlib.sha256(original).hexdigest()),
            },
        }
    )
    operate({"op": "verify", "id": "OGM-001", "evidence": "Unchanged source"})
    (operational.store.root / "settings.json").write_bytes(original + b"\n")
    assert operational.evaluate("OGM-001")["result"] == "FAIL"


def _second_lane(service, apply):
    (service.store.root / "dependency.json").write_text('{"retries":3}', encoding="utf-8")
    apply(
        {
            "op": "add",
            "register": "overlord",
            "row": {
                "ID": "OVR-009",
                "AssetType": "FILE",
                "Path": "dependency.json",
                "Purpose": "Dependency",
            },
        }
    )
    apply(
        {
            "op": "pace",
            "nodule": {
                "ID": "NDL-002",
                "NoduleName": "second",
                "Lane": "second",
                "Intent": "Second contract",
                "ContextPolicy": "REQUIRED",
                "UserRequest": "Dependency retries at least 2.",
                "TargetOVR": "OVR-009",
                "AbsorptionCriteria": "Rule holds",
            },
            "tasks": [
                {"ID": "PAC-002", "Title": "Second", "DoD": "Rule holds", "OVRRefs": "OVR-009"}
            ],
            "requirements": [
                {
                    "ID": "OGM-002",
                    "Title": "Second",
                    "Requirement": "Dependency retries at least 2",
                    "Authority": "USER",
                    "OriginText": "Dependency retries at least 2.",
                    "RuleType": "json_ge",
                    "RuleSubject": "OVR-009",
                    "RuleSelector": "/retries",
                    "RuleValue": "2",
                    "OVRRefs": "OVR-009",
                }
            ],
        }
    )
    apply(
        {"op": "verify", "id": "OGM-002", "evidence": "Observed dependency"},
        context=service.context("PAC-002")["receipt"],
    )


def test_dependency_asset_brings_its_rules(operational, operate, apply):
    _second_lane(operational, apply)
    operate({"op": "set", "id": "OVR-007", "fields": {"Requires": "OVR-009"}})
    packet = operational.context("PAC-001")
    assert packet["complete"] and "OGM-002" in packet["required_ids"]
    assert "OGM-002" in {r["id"] for r in packet["rules"]}


def test_refresh_respects_task_scope(operational, operate, apply):
    _second_lane(operational, apply)
    (operational.store.root / "dependency.json").write_text('{"retries":0}', encoding="utf-8")
    assert "OGM-002" not in operational.context("PAC-001")["required_ids"]
    changed = operate({"op": "refresh", "id": "PAC-001"})["changed_ids"]
    assert "OGM-002" not in changed
    assert (
        operational.query("organism", where={"ID": "OGM-002"})["rows"][0]["Status"]
        == "VALIDATED_COMPLETE"
    )


def test_broken_dependency_blocks_completion_and_absorption(operational, operate, apply):
    _second_lane(operational, apply)
    operate({"op": "set", "id": "OGM-001", "fields": {"BlockedByOGM": "OGM-002"}})
    operate(
        {"op": "verify", "id": "OGM-001", "evidence": "Observed contract"},
        {"op": "transition", "id": "PAC-001", "status": "DOING"},
        {"op": "transition", "id": "PAC-001", "status": "REVIEW"},
    )
    (operational.store.root / "dependency.json").write_text('{"retries":0}', encoding="utf-8")
    assert operational.evaluate("OGM-001")["freshness"] == "STALE"
    with pytest.raises(ValueError, match="current"):
        operate({"op": "transition", "id": "PAC-001", "status": "DONE", "evidence": "Cannot pass"})
    assert operational.query("nodule", where={"ID": "NDL-001"})["rows"][0]["Status"] == "ACTIVE"


def test_migration_repairs_legacy_acceptance_without_inventing_evidence(paced, apply):
    from pacer_mcp.store import encode_csv

    apply(
        {
            "op": "transition",
            "id": "OGM-001",
            "status": "VALIDATED_COMPLETE",
            "evidence": "Historical audit",
        }
    )
    with paced.store.locked():
        snapshot = paced.store.load()
    snapshot.tables["overlord"][0]["OGMRefs"] = "OGM-001"
    (paced.store.root / "overlord.PACER.csv").write_bytes(
        encode_csv(snapshot.headers["overlord"], snapshot.tables["overlord"])
    )
    r = paced.onboard()
    paced.migrate(actor="tester", revision=r["revision"], onboarding=r["onboarding"], preview=False)
    row = paced.query(
        "organism",
        where={"ID": "OGM-001"},
        fields=["Status", "OVRRefs", "Authority", "EvidenceBindings"],
    )["rows"][0]
    assert row["Status"] == "VALIDATED_COMPLETE" and row["OVRRefs"] == "OVR-001"
    assert row["Authority"] == "LEGACY" and not row["EvidenceBindings"]


def test_explicit_legacy_adoption_preserves_meaning_and_migration_cannot_refresh(
    operational, operate
):
    """Re-adoption requires actual verification; schema migration cannot renew stale sources."""
    original = operational.query("organism", fields=["Requirement"])["rows"][0]["Requirement"]
    operate({"op": "verify", "id": "OGM-001", "evidence": "Reviewed source rule"})
    (operational.store.root / "settings.json").write_text('{"retries":4}', encoding="utf-8")
    assert operational.evaluate("OGM-001")["freshness"] == "STALE"
    state = operational.onboard()
    operational.migrate(
        actor="tester", revision=state["revision"], onboarding=state["onboarding"], preview=False
    )
    assert operational.evaluate("OGM-001")["freshness"] == "STALE"
    assert (
        operational.query("organism", fields=["Requirement"])["rows"][0]["Requirement"] == original
    )
    operate({"op": "verify", "id": "OGM-001", "evidence": "Fresh source evaluation"})
    assert operational.evaluate("OGM-001")["freshness"] == "CURRENT"


def test_migration_does_not_rewrite_absorbed_history(operational, operate):
    operate(
        {"op": "verify", "id": "OGM-001", "evidence": "Current source checked"},
        {"op": "transition", "id": "PAC-001", "status": "DOING"},
        {"op": "transition", "id": "PAC-001", "status": "REVIEW"},
        {"op": "transition", "id": "PAC-001", "status": "DONE", "evidence": "Checked"},
        {"op": "absorb", "id": "NDL-001", "evidence": "Checked"},
    )
    path = operational.store.root / "archive/nodules/NDL-001.PACER.csv"
    before = path.read_bytes()
    state = operational.onboard()
    operational.migrate(
        actor="tester", revision=state["revision"], onboarding=state["onboarding"], preview=False
    )
    assert path.read_bytes() == before


def test_final_batch_cannot_absorb_then_invalidate_evidence(operational, operate):
    operate({"op": "verify", "id": "OGM-001", "evidence": "Observed"})
    before = operational.onboard()["revision"]
    with pytest.raises(ValueError, match="current|basis"):
        operate(
            {"op": "transition", "id": "PAC-001", "status": "DOING"},
            {"op": "transition", "id": "PAC-001", "status": "REVIEW"},
            {"op": "transition", "id": "PAC-001", "status": "DONE", "evidence": "Checked"},
            {"op": "absorb", "id": "NDL-001", "evidence": "Checked"},
            {"op": "set", "id": "OVR-007", "fields": {"Exports": "changed-interface"}},
        )
    assert operational.onboard()["revision"] == before


@pytest.mark.parametrize("task", ["PAC-001", "PAC-002"])
def test_refresh_can_demote_dependent_rules_across_lanes(operational, operate, apply, task):
    _second_lane(operational, apply)
    operate({"op": "set", "id": "OGM-001", "fields": {"BlockedByOGM": "OGM-002"}})
    operate({"op": "verify", "id": "OGM-001", "evidence": "Contract checked"})
    (operational.store.root / "dependency.json").write_text('{"retries":0}', encoding="utf-8")
    packet = operational.context(task)
    assert {"OGM-001", "OGM-002"} <= set(packet["required_ids"])
    result = apply({"op": "refresh", "id": task}, context=packet["receipt"])
    assert {"OGM-001", "OGM-002"} <= set(result["changed_ids"])
    assert operational.validate()["valid"]
    assert all(
        row["Status"] != "VALIDATED_COMPLETE" for row in operational.query("organism")["rows"]
    )
