from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/cbrc_evaluate.py"
spec = importlib.util.spec_from_file_location("cbrc_evaluate", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def row(actual=0.04, bound=0.05, epsilon=0.06, fallback=False):
    return {
        "scene_id": "scene",
        "revision_id": "rev",
        "method": "CBRC",
        "edit_class": "gaussian",
        "changed_fraction": 0.02,
        "coupling_regime": "low",
        "hard_closure_nodes": 2,
        "repair_cone_nodes": 5,
        "total_nodes": 100,
        "fallback_full": fallback,
        "stable": True,
        "planner_work": 5,
        "full_work": 100,
        "qois": {
            "rgb_linf": {
                "epsilon": epsilon,
                "certified_bound": bound,
                "measured_full_reference_error": actual,
            }
        },
    }


class CBRCEvaluationTests(unittest.TestCase):
    def test_valid_certificate_passes(self):
        result = mod.evaluate([row()])
        self.assertTrue(result["pass"])
        self.assertEqual(result["certificateViolations"], [])

    def test_actual_above_bound_fails_entire_set(self):
        result = mod.evaluate([row(actual=0.051, bound=0.05)])
        self.assertFalse(result["pass"])
        self.assertFalse(result["gates"]["C2NoCertificateViolations"])

    def test_bound_or_actual_above_epsilon_fails(self):
        result = mod.evaluate([row(actual=0.07, bound=0.08, epsilon=0.06)])
        self.assertFalse(result["pass"])
        self.assertFalse(result["gates"]["C3NoCertifiedToleranceViolations"])

    def test_fallback_rows_are_kept(self):
        result = mod.evaluate([row(fallback=True)])
        self.assertTrue(result["pass"])
        self.assertEqual(result["fullFallbackCount"], 1)


if __name__ == "__main__":
    unittest.main()
