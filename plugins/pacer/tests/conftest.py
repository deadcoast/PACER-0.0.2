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


@pytest.fixture
def operational(project, apply):
    """A real project with a bounded numeric contract and unrelated source."""
    (project.store.root / "settings.json").write_text(
        '{"retries":3,"name":"PACER"}', encoding="utf-8"
    )
    (project.store.root / "unrelated.txt").write_text("not a dependency", encoding="utf-8")
    apply(
        *[
            {
                "op": "add",
                "register": "overlord",
                "row": {
                    "ID": row_id,
                    "AssetType": "FILE",
                    "Path": path,
                    "Purpose": purpose,
                },
            }
            for row_id, path, purpose in [
                ("OVR-007", "settings.json", "Runtime settings"),
                ("OVR-008", "unrelated.txt", "Unrelated source"),
            ]
        ]
    )
    apply(
        {
            "op": "pace",
            "nodule": {
                "ID": "NDL-001",
                "NoduleName": "retry-contract",
                "Lane": "main",
                "Intent": "Keep retries bounded",
                "TargetOVR": "OVR-007",
                "ContextPolicy": "REQUIRED",
                "UserRequest": "Retries must be at least 2.",
                "AbsorptionCriteria": "Rule verified against source",
            },
            "tasks": [
                {
                    "ID": "PAC-001",
                    "Title": "Maintain retries",
                    "DoD": "Rule holds",
                    "OVRRefs": "OVR-007",
                }
            ],
            "requirements": [
                {
                    "ID": "OGM-001",
                    "Title": "Retry lower bound",
                    "Requirement": "Retries must be at least 2",
                    "Authority": "USER",
                    "OriginText": "Retries must be at least 2.",
                    "RuleType": "json_ge",
                    "RuleSubject": "OVR-007",
                    "RuleSelector": "/retries",
                    "RuleValue": "2",
                    "OVRRefs": "OVR-007",
                }
            ],
        }
    )
    return project


@pytest.fixture
def operate(operational):
    """Use a freshly retrieved context receipt at the public write boundary."""

    def run(*operations, **options):
        receipt = operational.onboard()
        context = operational.context("PAC-001", max_bytes=100_000)
        return operational.apply(
            list(operations),
            actor="tester",
            revision=receipt["revision"],
            onboarding=receipt["onboarding"],
            context=context["receipt"],
            **options,
        )

    return run
