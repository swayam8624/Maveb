from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "experiments/cbrc_baseline_suite.py"
spec = importlib.util.spec_from_file_location("cbrc_baseline_suite", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def graph():
    return {
        "nodes": [
            {"id": "edit", "work": 1.0, "true_change_bound": 1.0},
            {"id": "middle", "work": 1.0, "true_change_bound": 0.5},
            {"id": "output", "work": 10.0, "true_change_bound": 0.0},
        ],
        "edges": [
            {
                "source": "edit",
                "target": "middle",
                "class": "analytic",
                "gain": 0.8,
                "bound_id": "gaussian-image-v1",
            },
            {
                "source": "middle",
                "target": "output",
                "class": "analytic",
                "gain": 0.8,
                "bound_id": "temporal-v1",
            },
        ],
        "hard_closure": ["edit"],
        "qois": [
            {"name": "rgb", "weights": {"output": 1.0}, "epsilon": 0.3}
        ],
        "changed_fraction": 0.01,
    }


class CBRCBaselineSuiteTests(unittest.TestCase):
    def test_frozen_baselines_are_all_present(self):
        result = mod.run(graph())
        expected = {
            "FULL",
            "EXACT",
            "RADIUS_0",
            "RADIUS_1",
            "RADIUS_2",
            "RADIUS_3",
            "FRACTION",
            "EMPIRICAL",
            "CBRC",
        }
        self.assertEqual(set(result["baselines"]), expected)

    def test_unsafe_baseline_is_retained_not_dropped(self):
        result = mod.run(graph())
        self.assertFalse(result["baselines"]["EXACT"]["passes"])
        self.assertIn("EXACT", result["baselines"])

    def test_cbrc_finds_certified_local_cone(self):
        result = mod.run(graph())
        self.assertTrue(result["baselines"]["CBRC"]["passes"])
        self.assertLess(
            result["baselines"]["CBRC"]["work"],
            result["baselines"]["FULL"]["work"],
        )

    def test_required_ablations_exist(self):
        result = mod.run(graph())
        self.assertIn("ABLATE_PREDECESSOR_CLOSURE", result["ablations"])
        self.assertIn("ABLATE_GAUSSIAN_ANALYTIC_BOUND", result["ablations"])
        self.assertIn("ABLATE_TEMPORAL_ANALYTIC_BOUND", result["ablations"])
        self.assertIn("ABLATE_QOI_SPECIALIZATION", result["ablations"])
        self.assertIn("ABLATE_NO_FALLBACK", result["ablations"])


if __name__ == "__main__":
    unittest.main()
