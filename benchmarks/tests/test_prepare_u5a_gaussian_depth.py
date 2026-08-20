#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import math
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SCRIPT = SCRIPTS / "prepare_u5a_gaussian_depth.py"
spec = importlib.util.spec_from_file_location("prepare_u5a_gaussian_depth", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class U5aGaussianDepthPreparationTests(unittest.TestCase):
    def test_target_indices_use_frozen_odd_sixteenths(self):
        self.assertEqual(module.target_indices(16), [1, 3, 5, 7, 9, 11, 13, 15])
        self.assertEqual(module.target_indices(8), list(range(8)))
        with self.assertRaises(ValueError):
            module.target_indices(7)

    def test_depth_only_sigma_ignores_confidence(self):
        depth = np.asarray([1.0, 2.0], dtype=np.float64)
        confidence = np.asarray([0, 255], dtype=np.uint8)
        actual = module.method_sigma(
            "depth-only-covariance",
            depth,
            confidence,
            floor=0.01,
            quadratic=0.002,
            penalty=6.0,
        )
        np.testing.assert_allclose(actual, [0.012, 0.018])

    def test_calibrated_sigma_uses_raw_u8_over_255(self):
        depth = np.asarray([1.0, 1.0, 1.0], dtype=np.float64)
        confidence = np.asarray([0, 128, 255], dtype=np.uint8)
        actual = module.method_sigma(
            "calibrated-covariance",
            depth,
            confidence,
            floor=1.0,
            quadratic=0.0,
            penalty=5.990146384791633,
        )
        expected = np.asarray(
            [
                1.0 + 5.990146384791633,
                1.0 + 5.990146384791633 * (1.0 - 128.0 / 255.0),
                1.0,
            ]
        )
        np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1.0e-15)

    def test_on_axis_covariance_matches_pixel_and_depth_variance(self):
        pose = np.eye(4, dtype=np.float64)
        depth = np.asarray([2.0], dtype=np.float64)
        xs = np.asarray([100.0])
        ys = np.asarray([80.0])
        sigma_z = np.asarray([0.05])
        pixel_sigma = 4.0 / math.sqrt(12.0)
        log_scale, quaternion = module.covariance_batch(
            xs,
            ys,
            depth,
            (200.0, 200.0, 100.0, 80.0),
            pose,
            sigma_z,
            pixel_sigma,
        )
        scales = np.exp(log_scale[0])
        expected_tangent = depth[0] / 200.0 * pixel_sigma
        np.testing.assert_allclose(
            np.sort(scales),
            np.sort([expected_tangent, expected_tangent, sigma_z[0]]),
            rtol=1.0e-12,
            atol=1.0e-12,
        )
        self.assertAlmostEqual(float(np.linalg.norm(quaternion[0])), 1.0, places=12)
        self.assertGreaterEqual(quaternion[0, 0], 0.0)

    def test_world_to_camera_payload_inverts_camera_to_world(self):
        pose = np.eye(4, dtype=np.float64)
        pose[:3, 3] = [1.0, 2.0, 3.0]
        flat, position = module.world_to_camera_payload(pose)
        matrix = np.asarray(flat).reshape(4, 4)
        np.testing.assert_allclose(matrix[:3, 3], [-1.0, -2.0, -3.0])
        self.assertEqual(position, [1.0, 2.0, 3.0])

    def test_gaussian_ply_has_only_required_degree_zero_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "one.ply"
            module.write_gaussian_ply(
                path,
                np.asarray([[1.0, 2.0, 3.0]]),
                np.log(np.asarray([[0.01, 0.02, 0.03]])),
                np.asarray([[1.0, 0.0, 0.0, 0.0]]),
                4.59511985013459,
            )
            text = path.read_text()
            self.assertIn("element vertex 1", text)
            for name in (
                "x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
                "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3",
            ):
                self.assertIn(f"property float {name}", text)
            self.assertNotIn("f_rest_", text)


if __name__ == "__main__":
    unittest.main()
