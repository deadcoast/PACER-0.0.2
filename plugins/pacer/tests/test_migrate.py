from pacer_mcp.migrate import from_05, from_v2
from pacer_mcp.validation import validate_web

OLD_TODO = {
    "ID": "PAC-001",
    "Title": "Do thing",
    "Phase": "Codex integration",
    "Status": "REVIEW",
    "DoD": "Thing done. More detail here.",
    "OVRRefs": "OVR-001",
    "OGMRefs": "OGM-001",
    "BlockedBy": "",
    "DependencyType": "",
    "NextAction": "review",
    "PreviousAttempts": "tried X, failed",
    "LearningNotes": "Y matters",
    "ApprovalState": "APPROVED",
    "ApprovalEvidence": "user: go",
    "Notes": "a | b | c",
    "ContextCheckpoint": "{}",
    "Tags": "#core",
}
OLD_OVR = {
    "ID": "OVR-001",
    "AssetType": "FILE",
    "Path": "README.md",
    "Symbol": "",
    "Purpose": "p" * 200,
    "Exports": "x",
    "Imports": "y",
    "Requires": "",
    "RequiredBy": "",
    "OGMRefs": "OGM-001",
    "PACRefs": "PAC-001",
    "NDLRefs": "",
    "Tags": "#core",
    "Notes": "n",
    "EvidenceFor": "",
}
OLD_OGM = {
    "ID": "OGM-001",
    "Title": "Req",
    "Status": "VALIDATED_COMPLETE",
    "Requirement": "r",
    "AcceptanceEvidence": "tests",
    "OVRRefs": "OVR-001",
    "Authority": "USER",
    "OriginText": "the user said",
    "RuleType": "manual",
    "EvidenceBindings": "{}",
    "Notes": "big",
    "Tags": "",
}
OLD_NDL = {
    "ID": "NDL-001",
    "NoduleName": "n",
    "Intent": "i",
    "Status": "ABSORBED",
    "TargetOVR": "OVR-001",
    "NewAssets": "",
    "OGMTargets": "OGM-001",
    "SpawnedPACs": "PAC-001",
    "AbsorptionCriteria": "done",
    "Lane": "main",
    "UserRequest": "",
    "Notes": "",
}


def test_from_05(registers):
    tables, events = from_05(
        {"todo": [OLD_TODO], "overlord": [OLD_OVR], "organism": [OLD_OGM], "nodule": []}, [OLD_NDL]
    )
    todo = {r["ID"]: r for r in tables["todo"]}
    pace = todo["PAC-001"]
    assert (
        pace["Kind"] == "PACE"
        and pace["Status"] == "INTEGRATED"
        and pace["Produce"] == "Thing done."
    )
    assert pace["In"] == "OVR-001" and pace["Binds"] == "OGM-001" and pace["Next"] == "integrate"
    phases = [r for r in tables["todo"] if r["Kind"] == "PHASE"]
    assert phases[0]["Title"] == "Codex integration" and pace["Pos"].startswith(
        phases[0]["Pos"] + "."
    )
    kinds = sorted(r["Kind"] for r in tables["decision"])
    assert kinds == ["FAILED", "LATCH", "LESSON"]
    latch = next(r for r in tables["decision"] if r["Kind"] == "LATCH")
    assert (
        latch["Latched"] == "true" and latch["Authority"] == "USER" and pace["Latch"] == latch["ID"]
    )
    ovr = tables["overlord"][0]
    assert len(ovr["Purpose"]) == 140 and ovr["Kind"] == "FILE" and ovr["Binds"] == "OGM-001"
    ogm = tables["organism"][0]
    assert (
        ogm["Status"] == "PACED_REQUIREMENT"
        and ogm["Origin"] == "the user said"
        and ogm["Evidence"] == ""
    )
    ndl = tables["nodule"][0]
    assert (
        ndl["Name"] == "n"
        and ndl["Request"] == "i"
        and ndl["Exit"] == "done"
        and ndl["Status"] == "ABSORBED"
    )
    assert any(
        e["op"] == "migrate" and e["id"] == "PAC-001" and "DoD" in e["detail"]["legacy"]
        for e in events
    )
    assert validate_web(tables, registers)["errors"] == []


V2 = """PACER::TODO version=2.0.0
PROJECT "Demo" maturity=integrated
GLOBAL G001 "Core" state=active
  SOURCE "README.md" role=authority
  PHASE P01 "Boot" state=integrated
    PACE M01 "rebase" state=done
    PACE M02 "wire" state=active
    EXIT coherent="boots"
  :nodule NDL-003 "shared pattern" state=active
  +approved NDL-003
  :loop⠁:
END
"""


def test_from_v2(registers):
    tables, events = from_v2(V2, registers)
    kinds = [(r["Kind"], r["Pos"], r["Status"]) for r in tables["todo"]]
    assert kinds == [
        ("AREA", "A1", "ACTIVE"),
        ("PHASE", "A1.P1", "INTEGRATED"),
        ("PACE", "A1.P1.01", "DONE"),
        ("PACE", "A1.P1.02", "ACTIVE"),
    ]
    assert tables["todo"][1]["Exit"] == "boots" and tables["todo"][1]["Tier"] == "integrated"
    assert "#m02" in tables["todo"][3]["Tags"] and tables["todo"][3]["Produce"] == "wire"
    assert (
        tables["overlord"][0]["Path"] == "README.md"
        and tables["overlord"][0]["Purpose"] == "authority"
    )
    assert tables["nodule"][0]["ID"] == "NDL-003" and tables["nodule"][0]["Spawned"] == "PAC-003"
    assert tables["decision"][0]["Kind"] == "LATCH" and tables["decision"][0]["Latched"] == "true"
    assert (registers / ".MIVIM.spec").exists()
    assert validate_web(tables, registers)["errors"] == []
