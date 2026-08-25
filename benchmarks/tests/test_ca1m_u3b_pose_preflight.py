#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT = SCRIPTS_DIR / "ca1m_u3b_pose_preflight.py"
sys.path.insert(0, str(SCRIPTS_DIR))
spec = importlib.util.spec_from_file_location("ca1m_u3b_pose_preflight", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class U3bPosePreflightTests(unittest.TestCase):
    def test_frozen_rule_accepts_five_of_five_without_legacy_minimum(self):
        validation = {
            "requestedPairCount": 16,
            "pairCount": 5,
            "cameraToWorldSupportedPairCount": 16,
            "inverseSupportedPairCount": 5,
            "cameraToWorldBetterPairCount": 5,
            "cameraToWorldMedianOfPairMedianErrorsMetres": 0.0012,
            "inverseMedianOfPairMedianErrorsMetres": 0.5,
        }
        self.assertTrue(module.frozen_pose_rule(validation))

    def test_frozen_rule_requires_majority(self):
        validation = {
            "requestedPairCount": 16,
            "pairCount": 5,
            "cameraToWorldSupportedPairCount": 16,
            "inverseSupportedPairCount": 5,
            "cameraToWorldBetterPairCount": 2,
            "cameraToWorldMedianOfPairMedianErrorsMetres": 0.0012,
            "inverseMedianOfPairMedianErrorsMetres": 0.5,
        }
        self.assertFalse(module.frozen_pose_rule(validation))

    def test_frozen_rule_requires_lower_scene_median(self):
        validation = {
            "requestedPairCount": 16,
            "pairCount": 5,
            "cameraToWorldSupportedPairCount": 16,
            "inverseSupportedPairCount": 5,
            "cameraToWorldBetterPairCount": 5,
            "cameraToWorldMedianOfPairMedianErrorsMetres": 0.6,
            "inverseMedianOfPairMedianErrorsMetres": 0.5,
        }
        self.assertFalse(module.frozen_pose_rule(validation))

    def test_zero_inverse_support_passes_only_with_all_frozen_direct_pairs(self):
        validation = {
            "requestedPairCount": 16,
            "pairCount": 0,
            "cameraToWorldSupportedPairCount": 16,
            "inverseSupportedPairCount": 0,
            "cameraToWorldBetterPairCount": 0,
            "cameraToWorldMedianOfPairMedianErrorsMetres": 0.0007,
            "inverseMedianOfPairMedianErrorsMetres": None,
        }
        self.assertTrue(module.frozen_pose_rule(validation))

        validation["cameraToWorldSupportedPairCount"] = 15
        self.assertFalse(module.frozen_pose_rule(validation))

    def test_inverse_none_with_nonzero_support_fails(self):
        validation = {
            "requestedPairCount": 16,
            "pairCount": 1,
            "cameraToWorldSupportedPairCount": 16,
            "inverseSupportedPairCount": 1,
            "cameraToWorldBetterPairCount": 1,
            "cameraToWorldMedianOfPairMedianErrorsMetres": 0.0007,
            "inverseMedianOfPairMedianErrorsMetres": None,
        }
        self.assertFalse(module.frozen_pose_rule(validation))


if __name__ == "__main__":
    unittest.main()
