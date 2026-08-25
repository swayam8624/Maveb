#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "benchmarks" / "scripts" / "freeze_reference_world_v1_acquisition.py"
COMMIT = "7b6c38ebd2d53f1d054dab810585d522d1a51618"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def plane(root: Path, path: str, data: bytes, width: int, height: int, stride: int, pixel_format: str) -> dict:
    destination = root / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return {
        "path": path,
        "sha256": sha256(data),
        "width": width,
        "height": height,
        "rowStrideBytes": stride,
        "pixelFormat": pixel_format,
        "byteCount": len(data),
    }


def make_capture(root: Path, frame_count: int = 2) -> Path:
    capture = root / "Reference.mavebcapture"
    capture.mkdir()
    frames = []
    for frame_id in range(1, frame_count + 1):
        stem = f"{frame_id:06d}"
        frames.append(
            {
                "frameID": frame_id,
                "arTimestampSeconds": 10.0 + frame_id,
                "hostTimestampNanoseconds": 1_000_000 + frame_id,
                "nativeImageOrientation": "landscapeRight",
                "mirrored": False,
                "cameraTrackingState": "normal",
                "cameraToWorld": [
                    1.0, 0.0, 0.0, 0.0,
                    0.0, 1.0, 0.0, 0.0,
                    0.0, 0.0, 1.0, 0.0,
                    0.01 * frame_id, 0.0, 0.0, 1.0,
                ],
                "calibration": {
                    "imageWidth": 4,
                    "imageHeight": 4,
                    "depthWidth": 2,
                    "depthHeight": 2,
                    "imageIntrinsics": [100.0, 0.0, 0.0, 0.0, 100.0, 0.0, 2.0, 2.0, 1.0],
                    "depthIntrinsics": [50.0, 0.0, 0.0, 0.0, 50.0, 0.0, 1.0, 1.0, 1.0],
                },
                "luma": plane(capture, f"color/{stem}.y8", bytes([frame_id]) * 16, 4, 4, 4, "y8"),
                "chroma": plane(capture, f"color/{stem}.cbcr8x2", bytes([frame_id + 1]) * 8, 2, 2, 4, "cbcr8x2"),
                "depth": plane(capture, f"depth/{stem}.f32", bytes([frame_id + 2]) * 16, 2, 2, 8, "depth-f32-metres"),
                "confidence": plane(capture, f"confidence/{stem}.u8", bytes([2]) * 4, 2, 2, 2, "arkit-confidence-u8"),
                "exposure": {"durationSeconds": 0.01, "exposureOffsetEV": 0.0},
            }
        )

    manifest = {
        "schemaVersion": 2,
        "sourceID": "fixture-source",
        "createdAt": "2026-08-26T00:00:00.000Z",
        "completedAt": "2026-08-26T00:00:02.000Z",
        "application": {"name": "MavebCapture", "version": "0.1.0"},
        "device": {"model": "iPad-fixture", "systemName": "iPadOS", "systemVersion": "26.0"},
        "coordinateSystem": {
            "camera": "ARKit right-handed: +X right, +Y up, -Z forward",
            "pose": "column-major camera-to-world 4x4 matrix",
            "depthUnit": "metres",
            "intrinsics": "3x3 column-major pixels",
        },
        "frames": frames,
        "statistics": {
            "acceptedFrames": frame_count,
            "droppedFrames": 0,
            "failedFrames": 0,
            "admissionRejectedFrames": 3,
        },
        "recovery": None,
    }
    (capture / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return capture


class ReferenceWorldAcquisitionFreezeTests(unittest.TestCase):
    def run_freezer(self, capture: Path, output: Path, minimum_frames: int = 2) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--capture",
                str(capture),
                "--scene-name",
                "Reference tabletop",
                "--ownership",
                "User-owned physical scene cleared for the Maveb v0.1 research release.",
                "--maveb-commit",
                COMMIT,
                "--minimum-frames",
                str(minimum_frames),
                "--output",
                str(output),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_valid_finalized_capture_freezes_deterministic_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = make_capture(root)
            output = root / "evidence.json"
            completed = self.run_freezer(capture, output)
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(output.read_text())
            self.assertEqual(payload["status"], "frozen-valid-acquisition")
            self.assertEqual(payload["capture"]["frameCount"], 2)
            self.assertEqual(payload["capture"]["confidenceFrameCount"], 2)
            self.assertEqual(payload["capture"]["referencedFileCount"], 9)
            self.assertTrue(payload["integrity"]["allReferencedPlaneHashesVerified"])
            self.assertFalse(payload["integrity"]["syntheticFallbackUsed"])
            self.assertRegex(payload["capture"]["manifestSha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(payload["capture"]["contentSetSha256"], r"^[0-9a-f]{64}$")

    def test_unfinished_capture_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = make_capture(root)
            (capture / "frames.ndjson").write_text("unfinished\n")
            output = root / "evidence.json"
            completed = self.run_freezer(capture, output)
            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse(output.exists())
            self.assertIn("not finalized", completed.stderr)

    def test_tampered_plane_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = make_capture(root)
            (capture / "depth/000001.f32").write_bytes(b"tampered payload")
            output = root / "evidence.json"
            completed = self.run_freezer(capture, output)
            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse(output.exists())
            self.assertTrue("file size" in completed.stderr or "SHA-256" in completed.stderr)

    def test_existing_evidence_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = make_capture(root)
            output = root / "evidence.json"
            first = self.run_freezer(capture, output)
            self.assertEqual(first.returncode, 0, msg=first.stderr)
            original = output.read_bytes()
            second = self.run_freezer(capture, output)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(output.read_bytes(), original)
            self.assertIn("refusing to overwrite", second.stderr)


if __name__ == "__main__":
    unittest.main()
