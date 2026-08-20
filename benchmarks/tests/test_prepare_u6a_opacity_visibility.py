#!/usr/bin/env python3

from __future__ import annotations

import math
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import prepare_u6a_opacity_visibility as u6a  # noqa: E402


class U6aOpacityVisibilityPreparationTests(unittest.TestCase):
    def test_frozen_u8_opacity_reference_values(self) -> None:
        confidence = np.asarray([0, 128, 255], dtype=np.uint8)
        values = u6a.opacity_probability(
            confidence,
            base_opacity=0.99,
            k=5.990146384791633,
        )
        expected = np.asarray(
            [
                0.020261082889362996,
                0.06239403876971809,
                0.99,
            ],
            dtype=np.float64,
        )
        np.testing.assert_allclose(values, expected, rtol=0.0, atol=1.0e-15)

    def test_opacity_logit_round_trip(self) -> None:
        probabilities = np.asarray([0.020261082889362996, 0.06239403876971809, 0.99])
        logits = u6a.opacity_logit(probabilities)
        reconstructed = 1.0 / (1.0 + np.exp(-logits))
        np.testing.assert_allclose(reconstructed, probabilities, rtol=0.0, atol=1.0e-15)

    def test_variant_changes_only_opacity_token(self) -> None:
        header = [
            "ply",
            "format ascii 1.0",
            "element vertex 2",
            *[f"property float {name}" for name in u6a.EXPECTED_PROPERTIES],
            "end_header",
        ]
        rows = [
            ["1", "2", "3", "0", "0", "0", "4.59511985", "-1", "-2", "-3", "1", "0", "0", "0"],
            ["4", "5", "6", "0", "0", "0", "4.59511985", "-4", "-5", "-6", "1", "0", "0", "0"],
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline.ply"
            variant = root / "variant.ply"
            baseline.write_text(
                "\n".join(header + [" ".join(row) for row in rows]) + "\n",
                encoding="utf-8",
            )
            logits = np.asarray([-3.0, -2.0], dtype=np.float64)
            parsed_header, parsed_rows, _ = u6a.parse_ascii_gaussian_ply(baseline)
            u6a.write_opacity_variant(variant, parsed_header, parsed_rows, logits)
            u6a.assert_only_opacity_changed(baseline, variant)
            _, variant_rows, _ = u6a.parse_ascii_gaussian_ply(variant)
            opacity_index = u6a.EXPECTED_PROPERTIES.index("opacity")
            for base, changed in zip(rows, variant_rows, strict=True):
                for column in range(len(base)):
                    if column == opacity_index:
                        self.assertNotEqual(base[column], changed[column])
                    else:
                        self.assertEqual(base[column], changed[column])

    def test_confidence_stream_matches_u5a_sampling_and_valid_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            width = 8
            height = 8
            depth = np.full((height, width), 1.0, dtype="<f4")
            depth[0, 4] = 0.0
            depth[4, 0] = 3.0
            intact = np.arange(width * height, dtype=np.uint8).reshape(height, width)
            shuffled = np.flip(intact, axis=1).copy()
            depth.tofile(root / "depth.f32")
            intact.tofile(root / "confidence.u8")
            shuffled.tofile(root / "shuffled.u8")
            manifest = {
                "volume": {
                    "minimumDepthMetres": 0.5,
                    "maximumDepthMetres": 2.0,
                },
                "frames": [
                    {
                        "width": width,
                        "height": height,
                        "depthPath": "depth.f32",
                        "confidencePath": "confidence.u8",
                        "shuffledConfidencePath": "shuffled.u8",
                    }
                ],
            }
            observed = u6a.confidence_stream(root, manifest, shuffled=False, stride=4)
            observed_shuffled = u6a.confidence_stream(root, manifest, shuffled=True, stride=4)
            np.testing.assert_array_equal(observed, np.asarray([0, 36], dtype=np.uint8))
            np.testing.assert_array_equal(observed_shuffled, np.asarray([7, 35], dtype=np.uint8))


if __name__ == "__main__":
    unittest.main()
