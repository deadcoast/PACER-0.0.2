"""Catch illegal workflow publication and lost cross-register history."""

from pathlib import Path

import pytest


def test_complete_request_survives_absorption(tmp_path: Path):
    from pacer_mcp.service import Service

    (tmp_path / "README.md").write_text("Example project", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Use PACER", encoding="utf-8")
    service = Service(tmp_path)
    service.initialize()
    receipt = service.onboard()
    result = service.apply(
        [
            {
                "op": "pace",
                "nodule": {
                    "ID": "NDL-001",
                    "NoduleName": "example",
                    "Intent": "Verify existing authority",
                    "Lane": "main",
                    "NewAssets": "",
                    "AbsorptionCriteria": "Authority audited",
                },
                "tasks": [{"ID": "PAC-001", "Title": "Audit authority", "DoD": "README inspected"}],
                "requirements": [
                    {
                        "ID": "OGM-001",
                        "Title": "Authority",
                        "Requirement": "README exists",
                        "Status": "SCAFFOLD",
                    }
                ],
            },
        ],
        actor="tester",
        revision=receipt["revision"],
        onboarding=receipt["onboarding"],
    )
    assert result["revision"] != receipt["revision"]
    assert service.query("todo", ready=True)["rows"][0]["ID"] == "PAC-001"
    receipt = service.onboard()
    service.apply(
        [
            {"op": "transition", "id": "PAC-001", "status": "DOING"},
            {"op": "transition", "id": "PAC-001", "status": "REVIEW"},
            {"op": "transition", "id": "PAC-001", "status": "DONE", "evidence": "README inspected"},
            {
                "op": "transition",
                "id": "OGM-001",
                "status": "VALIDATED_COMPLETE",
                "evidence": "2026-09-14 README inspection passed",
            },
            {"op": "absorb", "id": "NDL-001", "evidence": "2026-09-14 authority audited"},
        ],
        actor="tester",
        revision=receipt["revision"],
        onboarding=receipt["onboarding"],
    )
    assert service.query("nodule", where={"Status": "ACTIVE"})["rows"] == []
    row = service.query("nodule", where={"ID": "NDL-001"}, fields=["ID", "Status", "AbsorbedAt"])[
        "rows"
    ][0]
    assert row["Status"] == "ABSORBED" and row["AbsorbedAt"].endswith("Z")
    assert (tmp_path / "archive/nodules/NDL-001.PACER.csv").is_file()
    assert "NDL-001" not in (tmp_path / "nodule.PACER.csv").read_text()
    assert service.validate()["valid"]


def test_illegal_transition_does_not_publish(tmp_path: Path):
    from pacer_mcp.service import Service

    (tmp_path / "README.md").write_text("Project", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Rules", encoding="utf-8")
    service = Service(tmp_path)
    service.initialize()
    receipt = service.onboard()
    with pytest.raises(ValueError, match="REFUSAL: Illegal transition TODO->DONE"):
        service.apply(
            [
                {
                    "op": "add",
                    "register": "todo",
                    "row": {"ID": "PAC-001", "Title": "Work", "DoD": "Proven"},
                },
                {"op": "transition", "id": "PAC-001", "status": "DONE"},
            ],
            actor="tester",
            revision=receipt["revision"],
            onboarding=receipt["onboarding"],
        )
    assert service.onboard()["revision"] == receipt["revision"]
