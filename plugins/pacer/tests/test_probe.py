import sys

from pacer_mcp.probe import (
    bound_paths,
    format_evidence,
    freshness,
    parse_evidence,
    run_probe,
    src_digest,
)
from pacer_mcp.schema import empty_row


def _web(root):
    (root / "a.txt").write_text("one")
    return {
        "todo": [],
        "nodule": [],
        "decision": [],
        "overlord": [
            empty_row(
                "overlord", {"ID": "OVR-001", "Path": "a.txt", "Kind": "FILE", "Purpose": "p"}
            )
        ],
        "organism": [
            empty_row(
                "organism",
                {
                    "ID": "OGM-001",
                    "Title": "t",
                    "Status": "SCAFFOLD",
                    "Requirement": "r",
                    "Binds": "OVR-001",
                    "Probe": f'"{sys.executable}" -c "print(42)"',
                },
            )
        ],
    }


def test_evidence_roundtrip():
    cell = format_evidence("abc1234", "1234567", 0, "89abcde", "2026-09-29T00:00:00Z")
    assert parse_evidence(cell) == {
        "rev": "abc1234",
        "src": "1234567",
        "exit": 0,
        "out": "89abcde",
        "at": "2026-09-29T00:00:00Z",
    }
    assert parse_evidence("garbage") is None


def test_run_probe_then_freshness(registers):
    web = _web(registers)
    ogm = web["organism"][0]
    assert bound_paths(ogm, web) == ["a.txt"]
    result = run_probe(ogm, web, registers, "tester")
    assert result["exit"] == 0 and result["freshness"] == "CURRENT"
    ogm["Evidence"] = result["evidence"]
    assert freshness(ogm, web, registers) == "CURRENT"
    assert (registers / result["output_path"]).read_text().strip().endswith("42")
    (registers / "a.txt").write_text("two")
    assert freshness(ogm, web, registers) == "STALE"
    assert src_digest(registers, ["a.txt"]) != parse_evidence(ogm["Evidence"])["src"]


def test_failing_probe_records_exit(registers):
    web = _web(registers)
    ogm = web["organism"][0]
    ogm["Probe"] = f'"{sys.executable}" -c "raise SystemExit(3)"'
    result = run_probe(ogm, web, registers, "tester")
    assert result["exit"] == 3 and result["freshness"] == "FAIL"
    ogm["Evidence"] = result["evidence"]
    assert freshness(ogm, web, registers) == "FAIL"
    assert freshness(empty_row("organism", {"ID": "OGM-002"}), web, registers) == "UNBOUND"
