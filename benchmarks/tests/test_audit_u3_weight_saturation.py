#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path
import unittest

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from audit_u3_weight_saturation import compute_weights  # noqa: E402


class WeightSaturationAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = {
            "minimumSigmaMetres": 0.001,
            "maximumSigmaMetres": 0.25,
            "depthNoiseFloorMetres": 0.010634156727771725,
            "depthNoiseQuadraticMetresPerMetreSquared": 0.004398048551220112,
            "sensorConfidencePenalty": 5.990146384791633,
            "poseTranslationFloorMetres": 0.001,
            "referenceSigmaMetres": 0.01,
            "minimumPrecisionWeight": 0.01,
            "maximumPrecisionWeight": 1.0,
        }

    def test_medium_and_low_confidence_hit_floor_by_two_metres(self) -> None:
        depth = np.asarray([2.0, 2.0, 2.0], dtype=np.float64)
        confidence = np.asarray([255, 128, 0], dtype=np.uint8)
        _, weights = compute_weights(depth, confidence, self.config)
        self.assertGreater(weights[0], 0.01)
        self.assertAlmostEqual(float(weights[1]), 0.01, places=12)
        self.assertAlmostEqual(float(weights[2]), 0.01, places=12)

    def test_all_confidence_levels_hit_floor_by_five_metres(self) -> None:
        depth = np.asarray([5.0, 5.0, 5.0], dtype=np.float64)
        confidence = np.asarray([255, 128, 0], dtype=np.uint8)
        _, weights = compute_weights(depth, confidence, self.config)
        np.testing.assert_allclose(weights, np.asarray([0.01, 0.01, 0.01]), atol=1e-12, rtol=0.0)

    def test_depth_only_ablation_removes_confidence_dependence(self) -> None:
        depth = np.asarray([1.0, 1.0, 1.0], dtype=np.float64)
        confidence = np.asarray([255, 128, 0], dtype=np.uint8)
        _, weights = compute_weights(
            depth,
            confidence,
            self.config,
            sensor_confidence_penalty=0.0,
        )
        np.testing.assert_allclose(weights, np.repeat(weights[0], 3), atol=1e-12, rtol=0.0)


if __name__ == "__main__":
    unittest.main()
