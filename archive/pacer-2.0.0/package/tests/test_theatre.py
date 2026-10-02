import unittest
from pathlib import Path
from pacer.parser import parse
from pacer.theatre import compile_theatre

ROOT = Path(__file__).parents[1]

class TheatreTests(unittest.TestCase):
    def test_theatre_is_bounded_to_selected_phase(self):
        p = parse(ROOT / "examples" / "REPLICATA_M01_M18.todo.PACER")
        out = compile_theatre(p, "P04")
        self.assertIn("M14", out)
        self.assertIn("M16", out)
        self.assertNotIn("M03", out)
        self.assertNotIn("scope authorship", out)
        self.assertIn(":loop⠁:", out)

    def test_active_theatre_selects_active_phase(self):
        p = parse(ROOT / "todo.PACER")
        out = compile_theatre(p)
        self.assertIn("P05", out)
        self.assertIn("Exercise package", out)

if __name__ == "__main__":
    unittest.main()
