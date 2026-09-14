"""Development evaluation must execute candidates and recover actual PACER state."""

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def development(monkeypatch):
    scripts = Path(__file__).resolve().parents[3] / "scripts"
    path = scripts / "evaluate_development.py"
    assert path.is_file(), "Development/resumption evaluator is required"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("evaluate_development", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_development_cases_replay_real_edits_and_lifecycle(development, tmp_path):
    cases = development.prepare_development_cases(tmp_path / "fixtures")
    assert {c["name"] for c in cases} == {
        "code_edit",
        "dependency_regression",
        "ambiguous_intent",
        "cold_resume",
        "subsequent_nodule",
    }
    for case in cases:
        result = development.replay_candidate(case, case["expected"], tmp_path / case["name"])
        assert result["passed"], result
        if case["name"] == "ambiguous_intent":
            assert result["status"] == "UNRESOLVED"
        else:
            assert result["status"] == "ABSORBED"
    cold = next(c for c in cases if c["name"] == "cold_resume")
    assert cold["packet"]["delta"]["changed_sources"] == ["calculator.py"]


def test_wrong_candidate_cannot_receive_success_for_preserved_state(development, tmp_path):
    case = development.prepare_development_cases(tmp_path / "fixtures")[0]
    wrong = case["expected"] | {"replacement": "def scale(value):\n    return value * 9\n"}
    result = development.replay_candidate(case, wrong, tmp_path / "wrong")
    assert not result["passed"]
    assert not development.score_candidate(wrong, case["expected"], result)["correct"]


def test_code_check_rejects_execution_outside_bounded_function(development):
    assert not development.check_code("import os\ndef scale(value):\n    return value * 2\n")
    assert development.check_code("def scale(value):\n    return 2 * value\n")
    assert not development.check_code("def scale(value, *extra):\n    return value * 2\n")
    assert not development.check_code("def scale(value, **extra):\n    return value * 2\n")
