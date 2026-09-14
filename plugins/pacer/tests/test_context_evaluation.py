"""The comparison must preserve facts and score actual decisions, not formatting."""

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def evaluation():
    path = Path(__file__).resolve().parents[3] / "scripts/evaluate_context.py"
    spec = importlib.util.spec_from_file_location("evaluate_context", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_serializations_preserve_the_same_facts(evaluation):
    packet = {
        "task": "PAC-001",
        "rules": [{"id": "OGM-001", "result": "FAIL"}],
        "tables": {
            "todo": {
                "columns": ["ID", "Instructions"],
                "rows": [["PAC-001", "Keep | and\nnewlines."]],
            }
        },
    }
    rendered = evaluation.render_formats(packet)
    assert json.loads(rendered["operational"]) == packet
    rows = json.loads(rendered["row_json"])
    assert rows["tables"]["todo"] == [{"ID": "PAC-001", "Instructions": "Keep | and\nnewlines."}]
    assert rows["rules"] == packet["rules"]
    assert "Keep &#124; and\\nnewlines." in rendered["markdown"]
    assert '"result":"FAIL"' in rendered["markdown"]


def test_scoring_rejects_missing_blockers_and_extra_impact(evaluation):
    expected = {
        "may_complete": False,
        "blockers": ["OGM-001"],
        "next_action": "implement",
        "impacted_assets": ["OVR-007"],
    }
    assert evaluation.score_answer(dict(expected), expected)["correct"]
    assert not evaluation.score_answer({**expected, "blockers": []}, expected)["correct"]
    assert not evaluation.score_answer(
        {**expected, "impacted_assets": ["OVR-007", "OVR-008"]}, expected
    )["correct"]


def test_cases_include_positive_control_stale_and_regressed_rules(evaluation, tmp_path):
    cases = evaluation.prepare_cases(tmp_path)
    assert len(cases) == 4
    by_name = {case["name"]: case for case in cases}
    assert by_name["current"]["expected"]["may_complete"]
    assert by_name["stale"]["packet"]["rules"][0]["result"] == "PASS"
    assert by_name["stale"]["expected"]["next_action"] == "verify"
    assert by_name["regressed"]["expected"]["next_action"] == "implement"
    assert by_name["unresolved"]["expected"]["next_action"] == "resolve"
