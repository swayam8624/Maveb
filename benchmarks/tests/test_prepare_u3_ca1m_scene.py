import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "benchmarks" / "scripts" / "prepare_u3_ca1m_scene.py"
SPEC = importlib.util.spec_from_file_location("prepare_u3_ca1m_scene", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
prepare = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = prepare
SPEC.loader.exec_module(prepare)


class PrepareU3Ca1mSceneTests(unittest.TestCase):
    def test_matrix_to_quaternion_round_trip_for_z_rotation(self):
        angle = np.deg2rad(60.0)
        rotation = np.asarray(
            [
                [np.cos(angle), -np.sin(angle), 0.0],
                [np.sin(angle), np.cos(angle), 0.0],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
        q = prepare.matrix_to_quaternion_wxyz(rotation)
        self.assertAlmostEqual(q[0], np.cos(angle / 2.0), places=12)
        self.assertAlmostEqual(q[1], 0.0, places=12)
        self.assertAlmostEqual(q[2], 0.0, places=12)
        self.assertAlmostEqual(q[3], np.sin(angle / 2.0), places=12)

    def test_shuffled_confidence_is_deterministic_distribution_preserving_permutation(self):
        frames = [
            np.asarray([[0, 128], [255, 0]], dtype=np.uint8),
            np.asarray([[255, 128], [128, 255]], dtype=np.uint8),
        ]
        first = prepare.shuffled_confidence(frames, 42)
        second = prepare.shuffled_confidence(frames, 42)
        self.assertTrue(all(np.array_equal(a, b) for a, b in zip(first, second)))
        before = np.sort(np.concatenate([frame.reshape(-1) for frame in frames]))
        after = np.sort(np.concatenate([frame.reshape(-1) for frame in first]))
        self.assertTrue(np.array_equal(before, after))
        self.assertFalse(all(np.array_equal(a, b) for a, b in zip(frames, first)))

    def test_dense_bounds_matches_frozen_quantile_and_max_axis_rule(self):
        depth = np.full((16, 16), 2.0, dtype=np.float64)
        pose = np.eye(4, dtype=np.float64)
        selected = [
            {
                "depth": depth,
                "intrinsics": (8.0, 8.0, 7.5, 7.5),
                "pose": pose,
            }
        ]
        bounds = prepare.dense_bounds(
            selected,
            pixel_stride=4,
            lower_quantile=0.005,
            upper_quantile=0.995,
            padding=0.12,
            minimum_voxel=0.02,
            maximum_axis_voxels=96,
        )
        self.assertGreaterEqual(bounds["sampledPoints"], 8)
        self.assertLessEqual(max(bounds["dimensions"]), 96)
        self.assertGreaterEqual(bounds["voxelSizeMetres"], 0.02)
        self.assertGreaterEqual(bounds["truncationDistanceMetres"], 4.0 * bounds["voxelSizeMetres"])


if __name__ == "__main__":
    unittest.main()
