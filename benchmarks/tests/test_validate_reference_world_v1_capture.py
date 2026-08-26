#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "benchmarks" / "scripts" / "validate_reference_world_v1_capture.py"
SPEC = importlib.util.spec_from_file_location("reference_world_validation", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
validation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validation)


class ReferenceWorldCaptureValidationTests(unittest.TestCase):
    def make_fixture(
        self,
        root: Path,
        *,
        negative_depth: bool = False,
        illegal_confidence: bool = False,
        fusion_frames: int = 2,
    ) -> tuple[Path, Path, Path]:
        capture = root / "reference.mavebcapture"
        (capture / "depth").mkdir(parents=True)
        (capture / "confidence").mkdir(parents=True)

        frames = []
        for frame_index in range(2):
            width, height, stride = 4, 2, 16
            depth_values = [1.0] * (width * height)
            if negative_depth and frame_index == 0:
                depth_values[0] = -1.0
            depth_path = capture / "depth" / f"{frame_index + 1:06d}.f32"
            depth_path.write_bytes(struct.pack("<" + "f" * len(depth_values), *depth_values))

            confidence_values = bytearray([2] * (width * height))
            if illegal_confidence and frame_index == 0:
                confidence_values[0] = 9
            confidence_path = capture / "confidence" / f"{frame_index + 1:06d}.u8"
            confidence_path.write_bytes(confidence_values)

            matrix = [
                1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                0.6 * frame_index, 0.0, 0.0, 1.0,
            ]
            frames.append(
                {
                    "cameraToWorld": matrix,
                    "depth": {
                        "path": f"depth/{frame_index + 1:06d}.f32",
                        "pixelFormat": "depth-f32-metres",
                        "width": width,
                        "height": height,
                        "rowStrideBytes": stride,
                    },
                    "confidence": {
                        "path": f"confidence/{frame_index + 1:06d}.u8",
                        "pixelFormat": "arkit-confidence-u8",
                        "width": width,
                        "height": height,
                        "rowStrideBytes": width,
                    },
                }
            )

        manifest = {"frames": frames}
        manifest_path = capture / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

        acquisition = root / "acquisition.json"
        acquisition.write_text(
            json.dumps(
                {
                    "status": "frozen-valid-acquisition",
                    "mavebCommit": "b" * 40,
                    "capture": {
                        "manifestSha256": manifest_sha,
                        "contentSetSha256": "c" * 64,
                        "sourceID": "fixture-source",
                        "frameCount": 2,
                    },
                }
            ),
            encoding="utf-8",
        )

        fuse = root / "aether-fuse"
        fuse.write_text(
            "#!/bin/sh\n"
            "cat <<'JSON'\n"
            + json.dumps(
                {
                    "ok": True,
                    "dryRun": True,
                    "frames": fusion_frames,
                    "automaticBounds": True,
                    "sampledPoints": 16,
                    "origin": [-1.0, -1.0, -1.0],
                    "dimensions": [200, 180, 160],
                    "voxelSizeMetres": 0.01,
                    "truncationDistanceMetres": 0.04,
                }
            )
            + "\nJSON\n",
            encoding="utf-8",
        )
        fuse.chmod(0o755)
        return capture, acquisition, fuse

    def test_valid_capture_passes_without_reconstruction(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            capture, acquisition, fuse = self.make_fixture(Path(temp))
            result = validation.build_validation(capture, acquisition, fuse, "a" * 40)
            self.assertEqual(result["status"], "validated-geometry-usable")
            self.assertTrue(result["integrity"]["fusionMaintainedPathDryRunPassed"])
            self.assertFalse(result["integrity"]["reconstructionIntegrated"])
            self.assertEqual(result["confidence"]["illegalCodeCount"], 0)

    def test_negative_metric_depth_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            capture, acquisition, fuse = self.make_fixture(Path(temp), negative_depth=True)
            with self.assertRaisesRegex(ValueError, "negative metric depth"):
                validation.build_validation(capture, acquisition, fuse, "a" * 40)

    def test_illegal_confidence_code_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            capture, acquisition, fuse = self.make_fixture(Path(temp), illegal_confidence=True)
            with self.assertRaisesRegex(ValueError, "illegal ARKit confidence"):
                validation.build_validation(capture, acquisition, fuse, "a" * 40)

    def test_maintained_fusion_frame_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            capture, acquisition, fuse = self.make_fixture(Path(temp), fusion_frames=1)
            with self.assertRaisesRegex(ValueError, "frame count differs"):
                validation.build_validation(capture, acquisition, fuse, "a" * 40)


if __name__ == "__main__":
    unittest.main()
