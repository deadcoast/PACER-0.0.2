import unittest
from pathlib import Path
from pacer.parser import parse
from pacer.audit import audit

ROOT = Path(__file__).parents[1]

class AuditTests(unittest.TestCase):
    def test_main_package_is_continuity_clean(self):
        p = parse(ROOT / "todo.PACER")
        self.assertEqual(audit(p), ["OK: no continuity anti-patterns detected by the advisory audit."])

    def test_legacy_example_detects_review_and_micro_gates(self):
        p = parse(ROOT / "examples" / "anti_pattern_independent_tasks.PACER")
        joined = "\n".join(audit(p))
        self.assertIn("REVIEW_PARKING", joined)
        self.assertIn("GATE_DENSITY", joined)
        self.assertIn("MICRO_GATE", joined)
        self.assertIn("CONTINUITY", joined)

if __name__ == "__main__":
    unittest.main()
