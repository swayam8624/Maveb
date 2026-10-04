import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "benchmarks" / "scripts" / "apply_u3_pose_manifest_gate.py"
SPEC = importlib.util.spec_from_file_location("apply_u3_pose_manifest_gate", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


class U3PoseManifestGateTests(unittest.TestCase):
    def test_five_of_five_pairs_pass_without_unregistered_minimum(self):
        validation = {
            "pairCount": 5,
            "cameraToWorldBetterPairCount": 5,
            "cameraToWorldMedianOfPairMedianErrorsMetres": 0.0011581770308350947,
            "inverseMedianOfPairMedianErrorsMetres": 0.5650567478700048,
        }
        self.assertTrue(gate.scene_passes_frozen_rule(validation))

    def test_majority_and_scene_median_are_both_required(self):
        validation = {
            "pairCount": 5,
            "cameraToWorldBetterPairCount": 2,
            "cameraToWorldMedianOfPairMedianErrorsMetres": 0.001,
            "inverseMedianOfPairMedianErrorsMetres": 0.5,
        }
        self.assertFalse(gate.scene_passes_frozen_rule(validation))

        validation["cameraToWorldBetterPairCount"] = 4
        validation["cameraToWorldMedianOfPairMedianErrorsMetres"] = 0.6
        self.assertFalse(gate.scene_passes_frozen_rule(validation))


if __name__ == "__main__":
    unittest.main()
