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


def make_row(index: int, *, fallback: bool, actual: float, epsilon: float = 0.01):
    return {
        "case_id": f"case-{index}",
        "scene_id": f"scene-{index % 4}",
        "changed_fraction": (index + 1) / 100.0,
        "fallback_full": fallback,
        "planner_work": 10.0 if not fallback else 100.0,
        "full_work": 100.0,
        "qois": {
            "rgb_linf": {
                "epsilon": epsilon,
                "certified_bound": 0.0 if fallback else min(actual + 0.001, epsilon),
                "measured_full_reference_error": 0.0 if fallback else actual,
            }
        },
        "candidateDiagnostics": {
            "candidateWork": 10.0,
            "candidateActualRgbError": actual,
            "candidateRgbBound": actual + 0.001,
        },
    }


class EmpiricalHeldoutTests(unittest.TestCase):
    def test_fixed_split_and_independent_safety_reporting(self):
        rows = []
        for index in range(30):
            rows.append(
                make_row(
                    index,
                    fallback=index >= 20,
                    actual=0.001 if index < 20 else 0.02,
                )
            )
        result = mod.evaluate(rows)
        self.assertGreater(result["trainCases"], 0)
        self.assertGreater(result["heldoutCases"], 0)
        self.assertEqual(
            result["safetyGroundTruth"],
            mod.SAFETY_GROUND_TRUTH,
        )
        self.assertIn("heldoutUnsafeFalseLocalRate", result)
        self.assertIn("heldoutConditionalUnsafeFalseLocalRate", result)
        self.assertIn("heldoutCBRCRejectedLocalRate", result)
        self.assertGreaterEqual(result["learnedThreshold"], 0.0)
        self.assertLessEqual(result["learnedThreshold"], 1.0)
        self.assertEqual(
            result["trainCases"] + result["heldoutCases"],
            len(rows),
        )

    def test_cbrc_fallback_is_not_automatically_called_unsafe(self):
        rows = [
            make_row(
                index,
                fallback=(index % 2 == 0),
                actual=0.001,
            )
            for index in range(30)
        ]
        result = mod.evaluate(rows)
        self.assertEqual(result["heldoutUnsafeFalseLocalCases"], [])
        self.assertEqual(result["heldoutUnsafeFalseLocalRate"], 0.0)
        self.assertGreater(len(result["heldoutCBRCRejectedLocalCases"]), 0)

    def test_split_is_deterministic(self):
        self.assertEqual(mod.split("same-case"), mod.split("same-case"))


if __name__ == "__main__":
    unittest.main()
