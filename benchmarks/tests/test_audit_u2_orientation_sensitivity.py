import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sys


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_u2_orientation_sensitivity.py"
SCRIPTS_DIR = MODULE_PATH.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
SPEC = importlib.util.spec_from_file_location("audit_u2_orientation_sensitivity", MODULE_PATH)
audit = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = audit
SPEC.loader.exec_module(audit)


class U2OrientationSensitivityTests(unittest.TestCase):
    def test_profiles_use_unique_frames_and_modal_transform(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "controlled.jsonl"
            rows = [
                {"scene": "a", "timestampNanoseconds": 1, "sidecarOrientationTransform": "rot90-cw", "orientationWitnessMedianAbsErrorMillimetres": 12.0},
                {"scene": "a", "timestampNanoseconds": 1, "sidecarOrientationTransform": "rot90-cw", "orientationWitnessMedianAbsErrorMillimetres": 12.0},
                {"scene": "a", "timestampNanoseconds": 2, "sidecarOrientationTransform": "rot90-cw", "orientationWitnessMedianAbsErrorMillimetres": 20.0},
                {"scene": "a", "timestampNanoseconds": 3, "sidecarOrientationTransform": "transpose", "orientationWitnessMedianAbsErrorMillimetres": 100.0},
            ]
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            profiles = audit.discover_frame_profiles(path)
            self.assertEqual(profiles["a"]["frameCount"], 3)
            self.assertEqual(profiles["a"]["modalTransform"], "rot90-cw")
            self.assertEqual(profiles["a"]["transformFrameCounts"], {"rot90-cw": 2, "transpose": 1})
            self.assertEqual(profiles["a"]["maximumWitnessMedianAbsErrorMillimetres"], 100.0)

    def test_subsets_are_diagnostic_filters(self):
        profiles = {"a": {"modalTransform": "rot90-cw"}}
        clean = {"scene": "a", "sidecarOrientationTransform": "rot90-cw", "orientationWitnessMedianAbsErrorMillimetres": 20.0}
        bad_witness = {"scene": "a", "sidecarOrientationTransform": "rot90-cw", "orientationWitnessMedianAbsErrorMillimetres": 100.0}
        odd_transform = {"scene": "a", "sidecarOrientationTransform": "transpose", "orientationWitnessMedianAbsErrorMillimetres": 20.0}
        self.assertTrue(audit.include_row(clean, "strict-intersection", profiles, 51.0))
        self.assertFalse(audit.include_row(bad_witness, "within-calibration-witness-envelope", profiles, 51.0))
        self.assertTrue(audit.include_row(bad_witness, "modal-transform-only", profiles, 51.0))
        self.assertFalse(audit.include_row(odd_transform, "modal-transform-only", profiles, 51.0))
        self.assertFalse(audit.include_row(odd_transform, "strict-intersection", profiles, 51.0))


if __name__ == "__main__":
    unittest.main()
