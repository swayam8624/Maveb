from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "research/experiments/cbrc_empirical_heldout.py"
spec = importlib.util.spec_from_file_location("cbrc_empirical_heldout", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


class EmpiricalHeldoutTests(unittest.TestCase):
    def test_fixed_split_and_safety_reporting(self):
        rows = []
        for index in range(30):
            rows.append(
                {
                    "case_id": f"case-{index}",
                    "scene_id": f"scene-{index % 4}",
                    "changed_fraction": (index + 1) / 100.0,
                    "fallback_full": index >= 20,
                    "planner_work": 10.0,
                    "full_work": 100.0,
                    "candidateDiagnostics": {"candidateWork": 10.0},
                }
            )
        result = mod.evaluate(rows)
        self.assertGreater(result["trainCases"], 0)
        self.assertGreater(result["heldoutCases"], 0)
        self.assertIn("heldoutUnsafeFalseLocalRate", result)
        self.assertGreaterEqual(result["learnedThreshold"], 0.0)
        self.assertLessEqual(result["learnedThreshold"], 1.0)
        self.assertEqual(
            result["trainCases"] + result["heldoutCases"],
            len(rows),
        )

    def test_split_is_deterministic(self):
        self.assertEqual(mod.split("same-case"), mod.split("same-case"))


if __name__ == "__main__":
    unittest.main()
