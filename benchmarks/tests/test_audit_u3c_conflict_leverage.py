#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

import numpy as np


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_u3c_conflict_leverage.py"
spec = importlib.util.spec_from_file_location("audit_u3c_conflict_leverage", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class U3cConflictLeverageTests(unittest.TestCase):
    def test_llround_matches_half_away_from_zero(self):
        values = np.asarray([-2.5, -1.5, -0.5, 0.5, 1.5, 2.5, 2.49])
        actual = module.llround_array(values)
        np.testing.assert_array_equal(actual, np.asarray([-3, -2, -1, 1, 2, 3, 2]))

    def test_nearest_quantile_resolves_half_ties_lower(self):
        values = np.asarray([0.0, 1.0, 2.0])
        self.assertEqual(module.nearest_tie_lower(values, 0.25), 0.0)
        self.assertEqual(module.nearest_tie_lower(values, 0.75), 1.0)

    def test_rowwise_spearman_detects_positive_and_negative_alignment(self):
        distances = np.asarray(
            [
                [-0.1, 0.0, 0.4, np.nan],
                [-0.4, 0.0, 0.1, np.nan],
            ],
            dtype=np.float64,
        )
        sigmas = np.asarray(
            [
                [1.0, 2.0, 3.0, np.nan],
                [3.0, 2.0, 1.0, np.nan],
            ],
            dtype=np.float64,
        )
        actual = module.rowwise_spearman(sigmas, distances)
        self.assertTrue(np.isfinite(actual[0]))
        self.assertTrue(np.isfinite(actual[1]))
        self.assertGreater(actual[0], 0.0)
        self.assertLess(actual[1], 0.0)

    def test_summarize_scene_exposes_all_four_categories(self):
        protocol = {
            "observationConstruction": {"minimumContributingViews": 2},
            "frozenUncertainty": {"sensorConfidencePenalty": 5.990146384791633},
            "sceneSummaries": {"quarterVoxelThreshold": 0.25},
        }
        manifest = {
            "scene": "synthetic",
            "videoId": "0",
            "volume": {
                "dimensions": [2, 2, 1],
                "voxelSizeMetres": 0.1,
                "truncationDistanceMetres": 0.4,
            },
        }
        distances = np.asarray(
            [
                [0.00, 0.05, np.nan],
                [0.00, 0.05, np.nan],
                [-0.20, 0.20, np.nan],
                [-0.20, 0.20, np.nan],
            ],
            dtype=np.float32,
        )
        confidences = np.asarray(
            [
                [1.0, 1.0, np.nan],
                [1.0, 0.0, np.nan],
                [1.0, 1.0, np.nan],
                [1.0, 0.0, np.nan],
            ],
            dtype=np.float32,
        )
        sigmas = np.asarray(
            [
                [1.0, 1.1, np.nan],
                [1.0, 2.0, np.nan],
                [1.0, 1.1, np.nan],
                [1.0, 2.0, np.nan],
            ],
            dtype=np.float32,
        )
        summary, arrays = module.summarize_scene(
            manifest,
            {
                "distances": distances,
                "confidences": confidences,
                "sigmas": sigmas,
                "voxelLinearIndex": np.arange(4),
            },
            protocol,
        )
        self.assertEqual(summary["surfaceActiveVoxelCount"], 4)
        self.assertEqual(
            summary["categoryCounts"],
            {
                "consensus-homogeneous-confidence": 1,
                "consensus-mixed-confidence": 1,
                "conflict-homogeneous-confidence": 1,
                "conflict-mixed-confidence": 1,
            },
        )
        np.testing.assert_array_equal(arrays["categoryCode"], np.asarray([0, 1, 2, 3], dtype=np.int8))
        self.assertAlmostEqual(summary["fractionConflictMixedConfidence"], 0.25)


if __name__ == "__main__":
    unittest.main()
