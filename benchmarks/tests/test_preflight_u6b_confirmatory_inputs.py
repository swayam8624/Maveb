#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from preflight_u6b_confirmatory_inputs import (  # noqa: E402
    inherited_pose_rule,
    orientation_accepted,
    orientation_scores,
)


class U6bConfirmatoryInputPreflightTests(unittest.TestCase):
    def test_pose_original_rule_requires_majority_and_lower_median(self) -> None:
        payload = {
            "mutuallyComparablePairCount": 7,
            "cameraToWorldWinsAmongComparable": 5,
            "cameraToWorldSupportedPairCount": 16,
            "inverseSupportedPairCount": 7,
            "cameraToWorldMedianOfSupportedPairMediansMetres": 0.02,
            "inverseMedianOfSupportedPairMediansMetres": 0.12,
        }
        self.assertTrue(inherited_pose_rule(payload))
        payload["cameraToWorldWinsAmongComparable"] = 3
        self.assertFalse(inherited_pose_rule(payload))

    def test_zero_inverse_support_requires_all_sixteen_direct_pairs(self) -> None:
        payload = {
            "mutuallyComparablePairCount": 0,
            "cameraToWorldWinsAmongComparable": 0,
            "cameraToWorldSupportedPairCount": 16,
            "inverseSupportedPairCount": 0,
            "cameraToWorldMedianOfSupportedPairMediansMetres": 0.02,
            "inverseMedianOfSupportedPairMediansMetres": None,
        }
        self.assertTrue(inherited_pose_rule(payload))
        payload["cameraToWorldSupportedPairCount"] = 15
        self.assertFalse(inherited_pose_rule(payload))

    def test_orientation_absolute_threshold_is_inclusive(self) -> None:
        scores = [
            {"medianAbsErrorMillimetres": 25.0},
            {"medianAbsErrorMillimetres": 26.0},
        ]
        self.assertTrue(orientation_accepted(scores))

    def test_orientation_relative_threshold_is_inclusive(self) -> None:
        scores = [
            {"medianAbsErrorMillimetres": 30.0},
            {"medianAbsErrorMillimetres": 40.0},
        ]
        self.assertTrue(orientation_accepted(scores))
        scores[0]["medianAbsErrorMillimetres"] = 30.0001
        self.assertFalse(orientation_accepted(scores))

    def test_orientation_scores_choose_correct_no_interpolation_transform(self) -> None:
        base = np.arange(400, dtype=np.uint16).reshape(20, 20) + 1000
        witness = np.rot90(base, 1)
        scores = orientation_scores(witness, base)
        self.assertGreaterEqual(len(scores), 4)
        self.assertEqual(scores[0]["transform"], "rot90-cw")
        self.assertEqual(scores[0]["medianAbsErrorMillimetres"], 0.0)
        self.assertEqual(scores[0]["validPixels"], 400)
        self.assertTrue(orientation_accepted(scores))


if __name__ == "__main__":
    unittest.main()
