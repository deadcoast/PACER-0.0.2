from pathlib import Path

import pytest
from pacer_mcp.service import Service


@pytest.fixture
def project(tmp_path: Path) -> Service:
    (tmp_path / "README.md").write_text("Project authority", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("PACER operating rules", encoding="utf-8")
    service = Service(tmp_path)
    service.initialize()
    return service


@pytest.fixture
def apply(project):
    def run(*operations, **options):
        receipt = project.onboard()
        return project.apply(
            list(operations),
            actor="tester",
            revision=receipt["revision"],
            onboarding=receipt["onboarding"],
            **options,
        )

    return run


@pytest.fixture
def paced(project, apply):
    apply(
        {
            "op": "pace",
            "nodule": {
                "ID": "NDL-001",
                "NoduleName": "first",
                "Intent": "Deliver a verified requirement",
                "Lane": "one",
                "TargetOVR": "OVR-001",
                "AbsorptionCriteria": "Verified requirement",
            },
            "tasks": [
                {"ID": "PAC-001", "Title": "First", "DoD": "First checked"},
                {
                    "ID": "PAC-002",
                    "Title": "Second",
                    "DoD": "Second checked",
                    "BlockedBy": "PAC-001",
                    "DependencyType": "hard",
                },
            ],
            "requirements": [
                {
                    "ID": "OGM-001",
                    "Title": "Feature",
                    "Requirement": "Verified behavior",
                    "Status": "SCAFFOLD",
                }
            ],
        }
    )
    return project
