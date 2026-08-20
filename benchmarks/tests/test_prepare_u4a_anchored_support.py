#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

import numpy as np


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_u4a_anchored_support.py"
spec = importlib.util.spec_from_file_location("prepare_u4a_anchored_support", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class U4aAnchoredSupportTests(unittest.TestCase):
    def test_anchor_support_field_uses_half_voxel_sigma_and_quarter_band(self):
        distances = np.asarray(
            [
                [0.10, 0.20, np.nan],
                [0.40, 0.20, np.nan],
                [0.00, 0.00, np.nan],
            ],
            dtype=np.float64,
        )
        sigmas = np.asarray(
            [
                [0.01, 0.03, np.nan],
                [0.01, 0.01, np.nan],
                [0.03, 0.03, np.nan],
            ],
            dtype=np.float64,
        )
        actual = module.anchor_support_field(distances, sigmas, voxel_size=0.04)
        np.testing.assert_array_equal(actual["anchorCount"], np.asarray([1, 2, 0]))
        self.assertAlmostEqual(actual["anchorDistance"][0], 0.10)
        self.assertAlmostEqual(actual["anchorDistance"][1], 0.30)
        self.assertTrue(np.isnan(actual["anchorDistance"][2]))
        np.testing.assert_array_equal(actual["supported"], np.asarray([True, False, False]))

    def test_pixel_surface_grid_indices_match_oracle_grid_rounding(self):
        depth = np.asarray([[1.0, 1.0]], dtype=np.float64)
        frame = {
            "intrinsics": [1.0, 1.0, 0.0, 0.0],
            "poseQuaternionWxyz": [1.0, 0.0, 0.0, 0.0],
            "poseTranslationMetres": [0.0, 0.0, 0.0],
        }
        volume = {
            "originMetres": [0.0, 0.0, 0.0],
            "voxelSizeMetres": 1.0,
            "dimensions": [3, 2, 3],
        }
        linear, inside = module.pixel_surface_grid_indices(depth, frame, volume)
        np.testing.assert_array_equal(inside, np.asarray([[True, True]]))
        np.testing.assert_array_equal(linear, np.asarray([[6, 7]]))

    def test_masked_confidence_preserves_original_byte_after_support_admission(self):
        depth = np.asarray([[1.0, 1.0]], dtype=np.float64)
        original = np.asarray([[128, 255]], dtype=np.uint8)
        support_confidence = np.asarray([[0, 255]], dtype=np.uint8)
        frame = {
            "intrinsics": [1.0, 1.0, 0.0, 0.0],
            "poseQuaternionWxyz": [1.0, 0.0, 0.0, 0.0],
            "poseTranslationMetres": [0.0, 0.0, 0.0],
        }
        volume = {
            "originMetres": [0.0, 0.0, 0.0],
            "voxelSizeMetres": 0.1,
            "dimensions": [20, 2, 20],
            "minimumDepthMetres": 0.05,
            "maximumDepthMetres": 20.0,
        }
        supported_grid = np.zeros(20 * 2 * 20, dtype=bool)
        linear, _ = module.pixel_surface_grid_indices(depth, frame, volume)
        supported_grid[linear[0, 0]] = True
        masked, diagnostics = module.mask_frame_confidence(
            depth,
            original,
            support_confidence,
            frame,
            volume,
            supported_grid,
            floor=0.01,
            quadratic=0.0,
            penalty=5.0,
            method="shuffled-calibrated-anchored-support",
        )
        self.assertEqual(int(masked[0, 0]), 128)
        self.assertEqual(int(masked[0, 1]), 255)
        self.assertEqual(diagnostics["validDepthObservationCount"], 2)
        self.assertEqual(diagnostics["finalAdmittedObservationCount"], 2)

    def test_unsupported_nonanchor_is_zeroed_without_changing_anchor_byte(self):
        depth = np.asarray([[1.0, 1.0]], dtype=np.float64)
        original = np.asarray([[128, 255]], dtype=np.uint8)
        support_confidence = np.asarray([[0, 255]], dtype=np.uint8)
        frame = {
            "intrinsics": [1.0, 1.0, 0.0, 0.0],
            "poseQuaternionWxyz": [1.0, 0.0, 0.0, 0.0],
            "poseTranslationMetres": [0.0, 0.0, 0.0],
        }
        volume = {
            "originMetres": [0.0, 0.0, 0.0],
            "voxelSizeMetres": 0.1,
            "dimensions": [20, 2, 20],
            "minimumDepthMetres": 0.05,
            "maximumDepthMetres": 20.0,
        }
        supported_grid = np.zeros(20 * 2 * 20, dtype=bool)
        masked, diagnostics = module.mask_frame_confidence(
            depth,
            original,
            support_confidence,
            frame,
            volume,
            supported_grid,
            floor=0.01,
            quadratic=0.0,
            penalty=5.0,
            method="shuffled-calibrated-anchored-support",
        )
        self.assertEqual(int(masked[0, 0]), 0)
        self.assertEqual(int(masked[0, 1]), 255)
        self.assertEqual(diagnostics["anchorObservationCount"], 1)
        self.assertEqual(diagnostics["suppressedNonAnchorObservationCount"], 1)


if __name__ == "__main__":
    unittest.main()
