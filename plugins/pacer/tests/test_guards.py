"""Wrong workflow branches must fail before any canonical bytes change."""

import csv
from datetime import UTC, datetime, timedelta

import pytest
from pacer_mcp.schema import HEADERS
from pacer_mcp.store import encode_csv


@pytest.mark.parametrize("action", ["remove", "set", "add"])
def test_inverse_requirement_basis_change_requires_demotion(paced, apply, action):
    apply(
        {"op": "link", "id": "OGM-001", "field": "OVRRefs", "target": "OVR-001"},
        {
            "op": "transition",
            "id": "OGM-001",
            "status": "VALIDATED_COMPLETE",
            "evidence": "checked",
        },
    )
    changes = {
        "remove": {"op": "set", "id": "OVR-001", "fields": {"OGMRefs": ""}},
        "set": {"op": "set", "id": "OVR-002", "fields": {"OGMRefs": "OGM-001"}},
        "add": {
            "op": "add",
            "register": "overlord",
            "row": {
                "ID": "OVR-007",
                "AssetType": "MODULE",
                "Path": "README.md",
                "Symbol": "example",
                "Purpose": "example",
                "OGMRefs": "OGM-001",
            },
        },
    }
    before = paced.onboard()["revision"]
    with pytest.raises(ValueError, match="Demote"):
        apply(changes[action])
    assert paced.onboard()["revision"] == before


def test_new_row_inverse_edge_can_be_removed_in_same_batch(paced, apply):
    apply(
        {
            "op": "add",
            "register": "todo",
            "row": {"ID": "PAC-003", "Title": "example", "DoD": "checked", "OVRRefs": "OVR-001"},
        },
        {"op": "link", "id": "OVR-001", "field": "PACRefs", "target": "PAC-003", "remove": True},
    )
    assert paced.query("todo", where={"ID": "PAC-003"}, fields=["OVRRefs"])["rows"] == [
        {"OVRRefs": ""}
    ]


@pytest.mark.parametrize("status", ["REVIEW", "TODO"])
def test_stale_work_cannot_advance_or_reset_clock(paced, apply, status):
    apply({"op": "transition", "id": "PAC-001", "status": "DOING"})
    with paced.store.locked():
        snapshot = paced.store.load()
        snapshot.tables["todo"][0]["StartedAt"] = (
            datetime.now(UTC) - timedelta(hours=49)
        ).isoformat()
        path = paced.store.root / "todo.PACER.csv"
        path.write_bytes(encode_csv(snapshot.headers["todo"], snapshot.tables["todo"]))
    before = paced.onboard()["revision"]
    with pytest.raises(ValueError, match="split"):
        apply({"op": "transition", "id": "PAC-001", "status": status})
    assert paced.onboard()["revision"] == before


@pytest.mark.parametrize(
    ("operation", "error"),
    [
        ({"op": "transition", "id": "PAC-002", "status": "DONE"}, "Illegal transition TODO->DONE"),
        (
            {"op": "transition", "id": "OGM-001", "status": "VALIDATED_COMPLETE"},
            "Evidence required",
        ),
        ({"op": "set", "id": "PAC-001", "fields": {"ID": "PAC-900"}}, "Protected field"),
        ({"op": "set", "id": "PAC-001", "fields": {"DoD": "easier"}}, "Protected field"),
        ({"op": "set", "id": "PAC-001", "fields": {"Notes": "erase"}}, "Protected field"),
        ({"op": "set", "id": "PAC-001", "fields": {"BlockedBy": "PAC-002"}}, "Circular dependency"),
        ({"op": "set", "id": "PAC-001", "fields": {"BlockedBy": "PAC-999"}}, "Unknown ID PAC-999"),
        ({"op": "set", "id": "PAC-001", "fields": {"DependencyType": "guess"}}, "DependencyType"),
        ({"op": "set", "id": "PAC-001", "fields": {"Tags": "#Uppercase"}}, "invalid Tags"),
        ({"op": "set", "id": "OVR-001", "fields": {"Path": "../escape.py"}}, "Unsafe"),
        ({"op": "set", "id": "OVR-001", "fields": {"Path": "C:/escape.py"}}, "Unsafe"),
        ({"op": "set", "id": "OVR-001", "fields": {"Path": "missing.py"}}, "does not exist"),
        ({"op": "absorb", "id": "NDL-001", "evidence": "checked"}, "Blocked by PAC-001;PAC-002"),
    ],
)
def test_rejected_batch_leaves_revision_unchanged(paced, apply, operation, error):
    before = paced.onboard()["revision"]
    with pytest.raises(ValueError, match=error):
        apply(operation)
    assert paced.onboard()["revision"] == before


def test_hard_gate_is_checked_at_done(paced, apply):
    apply(
        {"op": "transition", "id": "PAC-002", "status": "DOING"},
        {"op": "transition", "id": "PAC-002", "status": "REVIEW"},
    )
    with pytest.raises(ValueError, match="Blocked by PAC-001"):
        apply({"op": "transition", "id": "PAC-002", "status": "DONE", "evidence": "checked"})
    assert paced.query("todo", where={"ID": "PAC-002"})["rows"][0]["Status"] == "REVIEW"


@pytest.mark.parametrize("kind", ["soft", "optional"])
def test_nonhard_blockers_do_not_gate_ready_or_done(paced, apply, kind):
    apply({"op": "set", "id": "PAC-002", "fields": {"DependencyType": kind}})
    assert [r["ID"] for r in paced.query("todo", ready=True)["rows"]] == ["PAC-001", "PAC-002"]
    apply(
        {"op": "transition", "id": "PAC-002", "status": "DOING"},
        {"op": "transition", "id": "PAC-002", "status": "REVIEW"},
        {"op": "transition", "id": "PAC-002", "status": "DONE", "evidence": "checked"},
    )
    assert paced.validate()["valid"]


def test_preview_and_stale_revision(paced, apply):
    receipt = paced.onboard()
    change = {"op": "append", "id": "PAC-001", "field": "Notes", "text": "A learning"}
    assert apply(change, preview=True)["preview"]
    assert paced.onboard()["revision"] == receipt["revision"]
    apply(change)
    with pytest.raises(ValueError, match="Stale revision"):
        paced.apply(
            [change], actor="other", revision=receipt["revision"], onboarding=receipt["onboarding"]
        )


def test_authority_change_invalidates_onboarding(paced):
    receipt = paced.onboard()
    (paced.store.root / "AGENTS.md").write_text("New rules", encoding="utf-8")
    with pytest.raises(ValueError, match="Stale onboarding"):
        paced.apply(
            [{"op": "append", "id": "PAC-001", "field": "Notes", "text": "change"}],
            actor="tester",
            revision=receipt["revision"],
            onboarding=receipt["onboarding"],
        )


@pytest.mark.parametrize(("lane", "target"), [("one", "OVR-002"), ("two", "OVR-001")])
def test_overlapping_lane_or_target_is_rejected(paced, apply, lane, target):
    with pytest.raises(ValueError, match="Nodule lane occupied"):
        apply(
            {
                "op": "pace",
                "nodule": {
                    "ID": "NDL-002",
                    "NoduleName": "second",
                    "Intent": "Competing work",
                    "Lane": lane,
                    "TargetOVR": target,
                    "AbsorptionCriteria": "checked",
                },
                "tasks": [{"ID": "PAC-003", "Title": "Competing", "DoD": "checked"}],
            }
        )


def test_reference_addition_and_removal_are_symmetric(paced, apply):
    apply({"op": "link", "id": "OVR-001", "field": "Requires", "target": "OVR-002"})
    row = paced.query("overlord", where={"ID": "OVR-002"}, fields=["RequiredBy"])["rows"][0]
    assert row["RequiredBy"] == "OVR-001"
    apply({"op": "link", "id": "OVR-001", "field": "Requires", "target": "OVR-002", "remove": True})
    assert paced.query("overlord", where={"ID": "OVR-002"}, fields=["RequiredBy"])["rows"] == [
        {"RequiredBy": ""}
    ]


def test_projection_pagination_and_graph_bounds(paced):
    page = paced.query("todo", fields=["ID"], limit=1)
    assert page["rows"] == [{"ID": "PAC-001"}] and page["next_offset"] == 1
    assert paced.query("todo", fields=["ID"], limit=1, offset=1)["rows"] == [{"ID": "PAC-002"}]
    graph = paced.graph("NDL-001", depth=3, limit=2)
    assert len(graph["ids"]) == 2 and graph["truncated"]
    with pytest.raises(ValueError, match="Unknown ID"):
        paced.graph("PAC-900")


def test_stale_work_split_preserves_parent_and_links_children(paced, apply):
    apply({"op": "transition", "id": "PAC-001", "status": "DOING"})
    path = paced.store.root / "todo.PACER.csv"
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    rows[0]["StartedAt"] = (datetime.now(UTC) - timedelta(hours=49)).isoformat()
    path.write_bytes(encode_csv(list(rows[0]), rows))
    with pytest.raises(ValueError, match="split"):
        apply({"op": "transition", "id": "PAC-001", "status": "REVIEW"})
    apply(
        {
            "op": "split",
            "id": "PAC-001",
            "children": [
                {"ID": "PAC-001A", "Title": "Part A", "DoD": "A checked"},
                {"ID": "PAC-001B", "Title": "Part B", "DoD": "B checked"},
            ],
        }
    )
    row = paced.query("todo", where={"ID": "PAC-001"})["rows"][0]
    assert row["Status"] == "TODO" and row["DoD"] == "First checked"
    assert row["BlockedBy"] == "PAC-001A;PAC-001B"
    assert paced.validate()["valid"]


@pytest.mark.parametrize("child_position", [0, 1])
def test_split_cannot_discard_parent_nodule(operational, operate, child_position):
    operate({"op": "transition", "id": "PAC-001", "status": "DOING"})
    children = [
        {"ID": "PAC-001A", "Title": "Part A", "DoD": "A checked"},
        {"ID": "PAC-001B", "Title": "Part B", "DoD": "B checked"},
    ]
    children[child_position].update(NDLRefs="", OGMRefs="", OVRRefs="")
    with operational.store.locked():
        before = operational.store.load().files
    with pytest.raises(ValueError, match="Cannot remove admitted nodule scope"):
        operate({"op": "split", "id": "PAC-001", "children": children})
    with operational.store.locked():
        assert operational.store.load().files == before


def test_split_cannot_drop_one_of_multiple_parent_nodules(paced, apply):
    apply(
        {
            "op": "pace",
            "nodule": {
                "ID": "NDL-002",
                "NoduleName": "shared-task",
                "Intent": "Track an additional requirement of the same task",
                "Lane": "two",
                "SpawnedPACs": "PAC-001",
                "AbsorptionCriteria": "Task checked",
            },
            "tasks": [],
        },
        {"op": "transition", "id": "PAC-001", "status": "DOING"},
    )
    before = paced.onboard()["revision"]
    with pytest.raises(ValueError, match="Cannot remove admitted nodule scope"):
        apply(
            {
                "op": "split",
                "id": "PAC-001",
                "children": [
                    {"ID": "PAC-001A", "Title": "Part A", "DoD": "A checked"},
                    {
                        "ID": "PAC-001B",
                        "Title": "Part B",
                        "DoD": "B checked",
                        "NDLRefs": "NDL-001",
                    },
                ],
            }
        )
    assert paced.onboard()["revision"] == before


@pytest.mark.parametrize("fields", [{}, {"NDLRefs": "NDL-001"}])
def test_split_retains_child_context_gate_and_parent_approval(operational, operate, fields):
    operate(
        {"op": "approval", "id": "PAC-001", "state": "APPROVED", "evidence": "Maintain retries"},
        {"op": "transition", "id": "PAC-001", "status": "DOING"},
    )
    operate(
        {
            "op": "split",
            "id": "PAC-001",
            "children": [
                {"ID": "PAC-001A", "Title": "Part A", "DoD": "A checked", **fields},
                {"ID": "PAC-001B", "Title": "Part B", "DoD": "B checked", **fields},
            ],
        }
    )
    parent = operational.query("todo", where={"ID": "PAC-001"})["rows"][0]
    assert parent["DoD"] == "Rule holds"
    assert parent["BlockedBy"] == "PAC-001A;PAC-001B"
    nodule = operational.query("nodule", where={"ID": "NDL-001"})["rows"][0]
    assert nodule["SpawnedPACs"] == "PAC-001;PAC-001A;PAC-001B"
    for child_id in ("PAC-001A", "PAC-001B"):
        child = operational.query(
            "todo",
            where={"ID": child_id},
            fields=["NDLRefs", "ApprovalState", "ApprovalEvidence"],
        )["rows"][0]
        assert child["NDLRefs"] == "NDL-001"
        assert child["ApprovalState"] == "APPROVED"
        assert child["ApprovalEvidence"] == (
            "Derived split within approved PAC-001: Maintain retries"
        )
        receipt = operational.onboard()
        options = {
            "actor": "tester",
            "revision": receipt["revision"],
            "onboarding": receipt["onboarding"],
        }
        operation = {"op": "transition", "id": child_id, "status": "DOING"}
        with pytest.raises(ValueError, match="Operational scope requires current task context"):
            operational.apply([operation], **options)
        context = operational.context(child_id)
        assert context["complete"]
        operational.apply([operation], context=context["receipt"], **options)
    assert operational.validate()["valid"]


def test_completed_nodule_does_not_prevent_truthful_regression(paced, apply):
    for row_id in ("PAC-001", "PAC-002"):
        apply(
            *[
                {"op": "transition", "id": row_id, "status": status, "evidence": "checked"}
                for status in ("DOING", "REVIEW", "DONE")
            ]
        )
    apply(
        {
            "op": "transition",
            "id": "OGM-001",
            "status": "VALIDATED_COMPLETE",
            "evidence": "checked",
        },
        {"op": "absorb", "id": "NDL-001", "evidence": "checked"},
    )
    apply(
        {
            "op": "transition",
            "id": "OGM-001",
            "status": "SCAFFOLD",
            "evidence": "Regression discovered after PAC-002; source needs repair",
        }
    )
    assert paced.validate()["valid"]
    assert paced.query("organism", fields=["Status", "AcceptanceEvidence"])["rows"] == [
        {"Status": "SCAFFOLD", "AcceptanceEvidence": ""}
    ]


def test_legacy_migration_preserves_custom_and_original_cells(paced):
    path = paced.store.root / "todo.PACER.csv"
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    legacy = HEADERS["todo"][:-5] + ["ProjectSpecific"]
    for row in rows:
        row["RelatedWork"] = "OGM-001;NDL-001;#core"
    path.write_bytes(encode_csv(legacy, [{k: r.get(k, "retained") for k in legacy} for r in rows]))
    receipt = paced.onboard()
    assert not receipt["validation"]["valid"]
    paced.migrate(
        actor="tester",
        revision=receipt["revision"],
        onboarding=receipt["onboarding"],
        preview=False,
    )
    row = paced.query("todo", fields=["ID", "ProjectSpecific", "DoD", "OGMRefs"], limit=1)["rows"][
        0
    ]
    assert row == {
        "ID": "PAC-001",
        "ProjectSpecific": "retained",
        "DoD": "First checked",
        "OGMRefs": "OGM-001",
    }


def test_accepted_requirement_cannot_change_without_demotion(paced, apply):
    apply(
        {"op": "transition", "id": "OGM-001", "status": "VALIDATED_COMPLETE", "evidence": "checked"}
    )
    with pytest.raises(ValueError, match="Demote"):
        apply({"op": "set", "id": "OGM-001", "fields": {"Requirement": "A new unbuilt behavior"}})


@pytest.mark.parametrize(
    "fields",
    [
        {"SpawnedPACs": "PAC-001"},
        {"OGMTargets": ""},
        {"AbsorptionCriteria": "easier"},
        {"TargetOVR": ""},
    ],
)
def test_nodule_cannot_discard_admitted_scope(paced, apply, fields):
    with pytest.raises(ValueError, match="scope|Protected"):
        apply({"op": "set", "id": "NDL-001", "fields": fields})


def test_inverse_reference_cannot_discard_nodule_scope(paced, apply):
    with pytest.raises(ValueError, match="scope"):
        apply({"op": "set", "id": "PAC-002", "fields": {"NDLRefs": ""}})


def test_new_asset_aliases_are_the_same_lane_target(paced, apply):
    apply({"op": "set", "id": "NDL-001", "fields": {"NewAssets": "src/future.py"}})
    with pytest.raises(ValueError, match="Nodule lane occupied"):
        apply(
            {
                "op": "pace",
                "nodule": {
                    "ID": "NDL-002",
                    "NoduleName": "conflict",
                    "Lane": "two",
                    "Intent": "Overlaps a planned file",
                    "NewAssets": "./src/future.py",
                    "AbsorptionCriteria": "checked",
                },
                "tasks": [{"ID": "PAC-003", "Title": "Next", "DoD": "Next checked"}],
            }
        )


def test_add_then_remove_reciprocal_link_in_one_batch(paced, apply):
    apply(
        {"op": "link", "id": "OVR-001", "field": "Requires", "target": "OVR-002"},
        {"op": "link", "id": "OVR-002", "field": "RequiredBy", "target": "OVR-001", "remove": True},
    )
    assert paced.query("overlord", where={"ID": "OVR-001"}, fields=["Requires"])["rows"] == [
        {"Requires": ""}
    ]
