import importlib.util
import json
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ca1m_uncertainty_samples.py"
SPEC = importlib.util.spec_from_file_location("ca1m_uncertainty_samples", MODULE_PATH)
sampler = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = sampler
SPEC.loader.exec_module(sampler)


class Ca1mUncertaintySampleTests(unittest.TestCase):
    def test_member_identity_matches_released_layout(self):
        self.assertEqual(
            sampler.member_identity("42444499/123456.wide/depth.png"),
            ("42444499", "123456", "wide/depth"),
        )
        self.assertEqual(
            sampler.member_identity("42444499/123456.wide/depth/confidence.tiff"),
            ("42444499", "123456", "wide/depth/confidence"),
        )
        self.assertEqual(
            sampler.member_identity("42444499/123456.gt/depth/K.json"),
            ("42444499", "123456", "gt/depth/k"),
        )

    def test_parse_intrinsics_uses_row_major_camera_matrix(self):
        matrix = [[500.0, 0.0, 128.0], [0.0, 510.0, 96.0], [0.0, 0.0, 1.0]]
        self.assertEqual(
            sampler.parse_intrinsics(json.dumps(matrix).encode()),
            (500.0, 510.0, 128.0, 96.0),
        )

    def test_pixel_mapping_uses_calibrated_rays_not_fixed_resize(self):
        source = (100.0, 100.0, 50.0, 40.0)
        target = (250.0, 200.0, 120.0, 80.0)
        x, y = sampler.project_pixel_between_intrinsics(60, 50, source, target)
        self.assertAlmostEqual(x, 145.0)
        self.assertAlmostEqual(y, 100.0)

    def test_confidence_refuses_undocumented_scale(self):
        self.assertEqual(sampler.confidence_value(0), 0.0)
        self.assertEqual(sampler.confidence_value(1), 1.0)
        with self.assertRaisesRegex(ValueError, "documented"):
            sampler.confidence_value(2)


if __name__ == "__main__":
    unittest.main()
