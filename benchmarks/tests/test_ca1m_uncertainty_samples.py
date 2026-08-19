import importlib.util
import json
from pathlib import Path
import sys
import tempfile
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

    def test_arkit_confidence_levels_are_preserved_and_normalized(self):
        self.assertEqual(sampler.confidence_level(0), 0)
        self.assertEqual(sampler.confidence_level(1), 1)
        self.assertEqual(sampler.confidence_level(2), 2)
        self.assertEqual(sampler.confidence_value(0), 0.0)
        self.assertEqual(sampler.confidence_value(1), 0.5)
        self.assertEqual(sampler.confidence_value(2), 1.0)
        with self.assertRaisesRegex(ValueError, "0/1/2"):
            sampler.confidence_value(3)

    def test_confidence_timestamp_uses_video_prefix_and_decimal_seconds(self):
        path = Path("42444499_2456.215.png")
        self.assertAlmostEqual(sampler.parse_confidence_timestamp(path, "42444499"), 2456.215)
        self.assertIsNone(sampler.parse_confidence_timestamp(path, "42444511"))

    def test_nearest_confidence_join_respects_tolerance(self):
        frames = [
            sampler.ConfidenceFrame(10.000, Path("a.png")),
            sampler.ConfidenceFrame(10.017, Path("b.png")),
            sampler.ConfidenceFrame(10.033, Path("c.png")),
        ]
        match = sampler.nearest_confidence_frame(frames, 10.018, 0.020)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match[0].path, Path("b.png"))
        self.assertAlmostEqual(match[1], 0.001)
        self.assertIsNone(sampler.nearest_confidence_frame(frames, 10.100, 0.020))

    def test_discover_confidence_frames_rejects_missing_video(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "42444499_1.000.png").write_bytes(b"not-an-image-needed-for-discovery")
            frames = sampler.discover_confidence_frames(root, "42444499")
            self.assertEqual(len(frames), 1)
            self.assertAlmostEqual(frames[0].timestamp_seconds, 1.0)
            with self.assertRaisesRegex(ValueError, "no ARKitScenes confidence"):
                sampler.discover_confidence_frames(root, "42444511")


if __name__ == "__main__":
    unittest.main()
