#!/usr/bin/env python3

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import run_u6a_opacity_visibility as u6a  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def target_record(index: int, render_sha: str) -> dict:
    return {
        "targetIndex": index,
        "timestampNanoseconds": index + 100,
        "renderSha256": render_sha,
        "render": {"targetIndex": index},
        "faroValidPixelCount": 100,
        "renderedFiniteOnFaroValidPixelCount": 80,
        "coverageFraction": 0.8,
        "absoluteDepthErrorMeanMetres": 0.04,
        "absoluteDepthErrorMedianMetres": 0.03,
        "absoluteDepthErrorP95Metres": 0.09,
        "within5cmFractionOfFaroValid": 0.6,
        "within10cmFractionOfFaroValid": 0.7,
    }


class U6aOpacityVisibilityRunnerTests(unittest.TestCase):
    def test_frozen_method_identities_and_counts(self) -> None:
        self.assertEqual(u6a.BASELINE_METHOD, "depth-only-fixed-opacity")
        self.assertEqual(
            u6a.NEW_METHODS,
            (
                "calibrated-relative-precision-opacity",
                "shuffled-relative-precision-opacity",
            ),
        )
        self.assertEqual(len(u6a.EXPECTED_SCENES), 5)

    def test_verify_and_copy_baseline_reuses_exact_u5a_render_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scene = "ca1m-test"
            render_dir = root / "scenes" / scene / "renders" / u6a.BASELINE_U5A_METHOD
            render_dir.mkdir(parents=True)
            records = []
            for index in range(8):
                path = render_dir / f"{index:02d}.f32"
                path.write_bytes(bytes([index + 1]) * 16)
                records.append(target_record(index, sha(path)))
            summary = u6a.scene_summary(records)
            u5a_scene = {
                "methods": {
                    u6a.BASELINE_U5A_METHOD: {
                        "gaussianSha256": "baseline-gaussian",
                        "primitiveCount": 24576,
                        "targets": records,
                        "sceneSummary": summary,
                    }
                }
            }
            target_manifest = {
                "targets": [
                    {"targetIndex": index, "timestampNanoseconds": index + 100}
                    for index in range(8)
                ]
            }
            copied = u6a.verify_and_copy_baseline(
                scene=scene,
                u5a_root=root,
                u5a_scene=u5a_scene,
                target_manifest=target_manifest,
            )
            self.assertTrue(copied["reusedFromU5a"])
            self.assertEqual(copied["primitiveCount"], 24576)
            self.assertEqual(copied["sceneSummary"], summary)
            self.assertEqual(
                [record["renderSha256"] for record in copied["targets"]],
                [record["renderSha256"] for record in records],
            )

    def test_verify_and_copy_baseline_rejects_changed_render_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scene = "ca1m-test"
            render_dir = root / "scenes" / scene / "renders" / u6a.BASELINE_U5A_METHOD
            render_dir.mkdir(parents=True)
            records = []
            for index in range(8):
                path = render_dir / f"{index:02d}.f32"
                path.write_bytes(bytes([index + 1]) * 16)
                records.append(target_record(index, sha(path)))
            summary = u6a.scene_summary(records)
            u5a_scene = {
                "methods": {
                    u6a.BASELINE_U5A_METHOD: {
                        "gaussianSha256": "baseline-gaussian",
                        "primitiveCount": 24576,
                        "targets": records,
                        "sceneSummary": summary,
                    }
                }
            }
            target_manifest = {
                "targets": [{"targetIndex": index} for index in range(8)]
            }
            (render_dir / "03.f32").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "baseline render SHA mismatch"):
                u6a.verify_and_copy_baseline(
                    scene=scene,
                    u5a_root=root,
                    u5a_scene=u5a_scene,
                    target_manifest=target_manifest,
                )


if __name__ == "__main__":
    unittest.main()
