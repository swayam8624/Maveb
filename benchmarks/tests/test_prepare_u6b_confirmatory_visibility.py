#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "benchmarks" / "scripts"
sys.path.insert(0, str(SCRIPTS))

SPEC = importlib.util.spec_from_file_location(
    "prepare_u6b_confirmatory_visibility",
    SCRIPTS / "prepare_u6b_confirmatory_visibility.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

from prepare_u3_ca1m_scene import shuffled_confidence
from prepare_u5a_gaussian_depth import write_gaussian_ply
from prepare_u6a_opacity_visibility import (
    assert_only_opacity_changed,
    opacity_logit,
    opacity_probability,
    parse_ascii_gaussian_ply,
    write_opacity_variant,
)


class U6bConfirmatoryVisibilityPreparationTests(unittest.TestCase):
    def test_frozen_method_order_and_sampling_bounds(self) -> None:
        self.assertEqual(
            MODULE.METHODS,
            (
                "depth-only-fixed-opacity",
                "calibrated-relative-precision-opacity",
                "shuffled-relative-precision-opacity",
            ),
        )
        self.assertEqual(MODULE.PIXEL_STRIDE, 4)
        self.assertEqual(MODULE.MIN_DEPTH_METRES, 0.05)
        self.assertEqual(MODULE.MAX_DEPTH_METRES, 20.0)
        self.assertEqual(MODULE.SOURCE_COUNT, 8)
        self.assertEqual(MODULE.TARGET_COUNT, 8)

    def test_raw_confidence_mapping_is_exact(self) -> None:
        raw = np.asarray([[0, 1, 2], [2, 1, 0]], dtype=np.uint8)
        mapped = MODULE.map_confidence(raw)
        np.testing.assert_array_equal(
            mapped,
            np.asarray([[0, 128, 255], [255, 128, 0]], dtype=np.uint8),
        )
        self.assertEqual(
            MODULE.confidence_histogram(mapped),
            {"0": 2, "128": 2, "255": 2},
        )

    def test_splitmix_shuffle_preserves_full_stream_distribution(self) -> None:
        frames = [
            np.asarray([[0, 128], [255, 0]], dtype=np.uint8),
            np.asarray([[255, 128], [128, 255]], dtype=np.uint8),
        ]
        shuffled = shuffled_confidence(frames, 42)
        intact_flat = np.concatenate([frame.reshape(-1) for frame in frames])
        shuffled_flat = np.concatenate([frame.reshape(-1) for frame in shuffled])
        self.assertEqual(
            MODULE.confidence_histogram(intact_flat),
            MODULE.confidence_histogram(shuffled_flat),
        )
        self.assertFalse(np.array_equal(intact_flat, shuffled_flat))

    def test_source_records_require_exact_eight_authorized_sources(self) -> None:
        scene = {
            "videoId": "42898811",
            "primaryEightViewSelection": [
                {
                    "sourceIndex": index,
                    "timestampNanoseconds": 1000 + index,
                    "sidecarMatched": True,
                    "orientationAccepted": True,
                    "confidenceLevelsAndShapeValid": True,
                }
                for index in range(8)
            ],
        }
        records = MODULE.source_records(scene)
        self.assertEqual(len(records), 8)
        scene["primaryEightViewSelection"][3]["orientationAccepted"] = False
        with self.assertRaisesRegex(ValueError, "not authorized"):
            MODULE.source_records(scene)

    def test_opacity_variants_change_only_opacity_column(self) -> None:
        positions = np.asarray(
            [[0.0, 0.0, 1.0], [1.0, 2.0, 3.0], [-1.0, 0.5, 2.0]],
            dtype=np.float64,
        )
        log_scales = np.log(
            np.asarray(
                [[0.01, 0.02, 0.03], [0.02, 0.03, 0.04], [0.03, 0.04, 0.05]],
                dtype=np.float64,
            )
        )
        quaternions = np.asarray(
            [[1.0, 0.0, 0.0, 0.0]] * 3,
            dtype=np.float64,
        )
        base = 0.99
        base_logit = float(np.log(base / (1.0 - base)))
        confidence = np.asarray([0, 128, 255], dtype=np.uint8)
        probabilities = opacity_probability(
            confidence,
            base_opacity=base,
            k=5.990146384791633,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = root / "baseline.ply"
            variant = root / "variant.ply"
            write_gaussian_ply(
                baseline,
                positions,
                log_scales,
                quaternions,
                base_logit,
            )
            header, rows, _ = parse_ascii_gaussian_ply(baseline)
            write_opacity_variant(
                variant,
                header,
                rows,
                opacity_logit(probabilities),
            )
            assert_only_opacity_changed(baseline, variant)
            _, baseline_rows, _ = parse_ascii_gaussian_ply(baseline)
            _, variant_rows, _ = parse_ascii_gaussian_ply(variant)
            opacity_index = 6
            self.assertTrue(
                any(
                    baseline_row[opacity_index] != variant_row[opacity_index]
                    for baseline_row, variant_row in zip(
                        baseline_rows,
                        variant_rows,
                        strict=True,
                    )
                )
            )


if __name__ == "__main__":
    unittest.main()
