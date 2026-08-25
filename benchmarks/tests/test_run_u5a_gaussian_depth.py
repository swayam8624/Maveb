#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SCRIPT = SCRIPTS / "run_u5a_gaussian_depth.py"
spec = importlib.util.spec_from_file_location("run_u5a_gaussian_depth", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class U5aGaussianDepthRunnerTests(unittest.TestCase):
    def test_frozen_method_order(self):
        self.assertEqual(
            module.METHODS,
            (
                "depth-only-covariance",
                "calibrated-covariance",
                "shuffled-calibrated-covariance",
            ),
        )

    def test_missing_rendered_depth_is_penalized_in_primary_denominator(self):
        faro = np.asarray([[1.0, 1.0], [1.0, 0.0]], dtype=np.float32)
        rendered = np.asarray([[1.01, np.inf], [1.20, np.inf]], dtype=np.float32)
        metrics = module.target_metrics(rendered, faro)
        self.assertEqual(metrics["faroValidPixelCount"], 3)
        self.assertEqual(metrics["renderedFiniteOnFaroValidPixelCount"], 2)
        self.assertAlmostEqual(metrics["coverageFraction"], 2.0 / 3.0)
        self.assertAlmostEqual(metrics["within5cmFractionOfFaroValid"], 1.0 / 3.0)
        self.assertAlmostEqual(metrics["within10cmFractionOfFaroValid"], 1.0 / 3.0)

    def test_nearest_tie_lower_matches_u3c_convention(self):
        self.assertEqual(module.nearest_tie_lower([0.0, 1.0], 0.5), 0.0)
        self.assertEqual(module.nearest_tie_lower([0.0, 1.0, 2.0], 0.5), 1.0)

    def test_scene_summary_averages_eight_target_views(self):
        targets = []
        for index in range(8):
            targets.append(
                {
                    "within5cmFractionOfFaroValid": index / 10.0,
                    "within10cmFractionOfFaroValid": index / 8.0,
                    "coverageFraction": 0.5,
                    "absoluteDepthErrorMeanMetres": 0.01 + index * 0.001,
                    "absoluteDepthErrorMedianMetres": 0.005 + index * 0.001,
                    "absoluteDepthErrorP95Metres": 0.02 + index * 0.001,
                }
            )
        summary = module.scene_summary(targets)
        self.assertAlmostEqual(summary["primaryWithin5cmFractionOfFaroValid"], 0.35)
        self.assertAlmostEqual(summary["coverageFractionMean"], 0.5)

    def test_bootstrap_is_deterministic(self):
        values = [-0.03, -0.01, 0.0, 0.02, 0.05]
        a = module.paired_bootstrap_median(values, replicates=2000, seed=42)
        b = module.paired_bootstrap_median(values, replicates=2000, seed=42)
        self.assertEqual(a, b)
        self.assertEqual(a["median"], 0.0)
        self.assertEqual(a["replicates"], 2000)
        self.assertEqual(a["seed"], 42)


if __name__ == "__main__":
    unittest.main()
