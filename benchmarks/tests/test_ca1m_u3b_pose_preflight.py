#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ca1m_u3b_pose_preflight.py"
spec = importlib.util.spec_from_file_location("ca1m_u3b_pose_preflight", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class U3bPosePreflightTests(unittest.TestCase):
    def test_frozen_rule_accepts_five_of_five_without_legacy_minimum(self):
        validation = {
            "pairCount": 5,
            "cameraToWorldBetterPairCount": 5,
            "cameraToWorldMedianOfPairMedianErrorsMetres": 0.0012,
            "inverseMedianOfPairMedianErrorsMetres": 0.5,
        }
        self.assertTrue(module.frozen_pose_rule(validation))

    def test_frozen_rule_requires_majority(self):
        validation = {
            "pairCount": 5,
            "cameraToWorldBetterPairCount": 2,
            "cameraToWorldMedianOfPairMedianErrorsMetres": 0.0012,
            "inverseMedianOfPairMedianErrorsMetres": 0.5,
        }
        self.assertFalse(module.frozen_pose_rule(validation))

    def test_frozen_rule_requires_lower_scene_median(self):
        validation = {
            "pairCount": 5,
            "cameraToWorldBetterPairCount": 5,
            "cameraToWorldMedianOfPairMedianErrorsMetres": 0.6,
            "inverseMedianOfPairMedianErrorsMetres": 0.5,
        }
        self.assertFalse(module.frozen_pose_rule(validation))


if __name__ == "__main__":
    unittest.main()
