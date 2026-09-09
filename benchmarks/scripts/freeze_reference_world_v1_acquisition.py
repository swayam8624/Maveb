#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

EXPECTED_MANIFEST_SCHEMA = 2
EXPECTED_APP_NAME = "MavebCapture"
EXPECTED_APP_VERSION = "0.1.0"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def finite_numbers(values: Any, expected_length: int, label: str) -> list[float]:
    require(isinstance(values, list), f"{label} must be an array")
    require(len(values) == expected_length, f"{label} must contain {expected_length} values")
    result = [float(value) for value in values]
    require(all(math.isfinite(value) for value in result), f"{label} contains a non-finite value")
    return result


def validate_pose(values: Any, label: str) -> None:
    matrix = finite_numbers(values, 16, label)
    require(abs(matrix[3]) <= 1e-4, f"{label} is not affine")
    require(abs(matrix[7]) <= 1e-4, f"{label} is not affine")
    require(abs(matrix[11]) <= 1e-4, f"{label} is not affine")
    require(abs(matrix[15] - 1.0) <= 1e-4, f"{label} is not affine")

    columns = [
        (matrix[0], matrix[1], matrix[2]),
        (matrix[4], matrix[5], matrix[6]),
        (matrix[8], matrix[9], matrix[10]),
    ]

    def dot(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
        return sum(a * b for a, b in zip(left, right))

    for index, column in enumerate(columns):
        require(abs(dot(column, column) - 1.0) <= 5e-3, f"{label} rotation column {index} is not unit length")
    require(abs(dot(columns[0], columns[1])) <= 5e-3, f"{label} rotation columns 0/1 are not orthogonal")
    require(abs(dot(columns[0], columns[2])) <= 5e-3, f"{label} rotation columns 0/2 are not orthogonal")
    require(abs(dot(columns[1], columns[2])) <= 5e-3, f"{label} rotation columns 1/2 are not orthogonal")

    c0, c1, c2 = columns
    determinant = (
        c0[0] * (c1[1] * c2[2] - c1[2] * c2[1])
        - c1[0] * (c0[1] * c2[2] - c0[2] * c2[1])
        + c2[0] * (c0[1] * c1[2] - c0[2] * c1[1])
    )
    require(0.98 <= determinant <= 1.02, f"{label} rotation determinant is not +1")


def validate_intrinsics(values: Any, label: str) -> None:
    matrix = finite_numbers(values, 9, label)
    require(matrix[0] > 0.0 and matrix[4] > 0.0, f"{label} has non-positive focal length")
    require(abs(matrix[2]) <= 1e-4 and abs(matrix[5]) <= 1e-4, f"{label} has invalid projective terms")
    require(abs(matrix[8] - 1.0) <= 1e-4, f"{label} has invalid homogeneous term")


def safe_capture_file(root: Path, relative_path: str) -> Path:
    require(relative_path != "", "capture plane path is empty")
    relative = Path(relative_path)
    require(not relative.is_absolute(), f"capture plane path is absolute: {relative_path}")
    require(".." not in relative.parts, f"capture plane path escapes root: {relative_path}")
    resolved_root = root.resolve()
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(f"capture plane path escapes root: {relative_path}") from error
    require(resolved.is_file(), f"capture plane is missing: {relative_path}")
    return resolved


def validate_plane(
    root: Path,
    plane: Any,
    *,
    label: str,
    expected_pixel_format: str,
    expected_width: int | None,
    expected_height: int | None,
    seen_paths: set[str],
) -> dict[str, Any]:
    require(isinstance(plane, dict), f"{label} must be an object")
    relative_path = str(plane.get("path", ""))
    require(relative_path not in seen_paths, f"duplicate capture plane path: {relative_path}")
    seen_paths.add(relative_path)

    path = safe_capture_file(root, relative_path)
    require(not path.is_symlink(), f"capture plane must not be a symlink: {relative_path}")

    pixel_format = plane.get("pixelFormat")
    require(pixel_format == expected_pixel_format, f"{label} pixel format changed: {pixel_format}")

    width = int(plane.get("width", 0))
    height = int(plane.get("height", 0))
    stride = int(plane.get("rowStrideBytes", 0))
    byte_count = int(plane.get("byteCount", -1))
    require(width > 0 and height > 0 and stride > 0, f"{label} has invalid dimensions/stride")
    if expected_width is not None:
        require(width == expected_width, f"{label} width does not match calibration")
    if expected_height is not None:
        require(height == expected_height, f"{label} height does not match calibration")

    active_bytes_per_row = {
        "y8": width,
        "arkit-confidence-u8": width,
        "cbcr8x2": width * 2,
        "depth-f32-metres": width * 4,
    }[expected_pixel_format]
    require(stride >= active_bytes_per_row, f"{label} row stride is too small")
    require(byte_count == stride * height, f"{label} byteCount does not match stride * height")
    require(path.stat().st_size == byte_count, f"{label} file size does not match manifest")

    expected_sha = str(plane.get("sha256", ""))
    require(bool(HEX64.fullmatch(expected_sha)), f"{label} has invalid SHA-256")
    actual_sha = sha256_file(path)
    require(actual_sha == expected_sha, f"{label} SHA-256 mismatch")

    return {
        "path": relative_path,
        "bytes": byte_count,
        "sha256": actual_sha,
    }


def content_set_sha(files: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(files, key=lambda item: item["path"]):
        digest.update(entry["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(entry["bytes"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(entry["sha256"].encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def build_evidence(
    capture: Path,
    *,
    scene_name: str,
    ownership: str,
    maveb_commit: str,
    minimum_frames: int,
) -> dict[str, Any]:
    capture = capture.resolve()
    require(capture.is_dir(), f"capture directory does not exist: {capture}")
    require(capture.suffix == ".mavebcapture", "capture directory must end in .mavebcapture")
    require(minimum_frames > 0, "minimum frame count must be positive")

    scene_name = scene_name.strip()
    ownership = ownership.strip()
    require(scene_name != "", "scene name must not be empty")
    require(ownership != "", "ownership/release statement must not be empty")
    for value, label in ((scene_name, "scene name"), (ownership, "ownership/release statement")):
        lowered = value.casefold()
        require("todo" not in lowered and "tbd" not in lowered and "placeholder" not in lowered,
                f"{label} contains placeholder text")

    maveb_commit = maveb_commit.strip().lower()
    require(bool(HEX40.fullmatch(maveb_commit)), "Maveb commit must be a full 40-character lowercase SHA")

    manifest_path = capture / "manifest.json"
    require(manifest_path.is_file(), "finalized capture is missing manifest.json")
    require(not (capture / "frames.ndjson").exists(), "capture is not finalized: frames.ndjson is still present")
    require(not (capture / "checkpoint.json").exists(), "capture is not finalized: checkpoint.json is still present")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(manifest.get("schemaVersion") == EXPECTED_MANIFEST_SCHEMA, "capture manifest schema changed")
    require(manifest.get("completedAt") not in (None, ""), "capture manifest is not finalized")
    require(str(manifest.get("sourceID", "")).strip() != "", "capture sourceID is empty")

    application = manifest.get("application")
    require(isinstance(application, dict), "capture application metadata is missing")
    require(application.get("name") == EXPECTED_APP_NAME, "capture was not produced by MavebCapture")
    require(application.get("version") == EXPECTED_APP_VERSION, "MavebCapture version changed")

    device = manifest.get("device")
    require(isinstance(device, dict), "capture device metadata is missing")
    for key in ("model", "systemName", "systemVersion"):
        require(str(device.get(key, "")).strip() != "", f"capture device {key} is empty")

    coordinate_system = manifest.get("coordinateSystem")
    require(isinstance(coordinate_system, dict), "capture coordinate-system metadata is missing")
    require(coordinate_system.get("depthUnit") == "metres", "capture depth unit is not metres")
    require("camera-to-world" in str(coordinate_system.get("pose", "")), "capture pose semantics changed")

    frames = manifest.get("frames")
    require(isinstance(frames, list), "capture frames must be an array")
    require(len(frames) >= minimum_frames,
            f"capture has {len(frames)} frames; minimum required is {minimum_frames}")

    statistics = manifest.get("statistics")
    require(isinstance(statistics, dict), "capture statistics are missing")
    require(int(statistics.get("acceptedFrames", -1)) == len(frames),
            "acceptedFrames does not match manifest frame count")
    for key in ("droppedFrames", "failedFrames"):
        require(int(statistics.get(key, -1)) >= 0, f"capture statistic {key} is invalid")
    admission_rejected = statistics.get("admissionRejectedFrames")
    if admission_rejected is not None:
        require(int(admission_rejected) >= 0, "capture admissionRejectedFrames is invalid")

    seen_paths: set[str] = set()
    referenced_files: list[dict[str, Any]] = []
    previous_host_timestamp = -1
    previous_ar_timestamp = -math.inf
    confidence_frames = 0

    for index, frame in enumerate(frames, start=1):
        require(isinstance(frame, dict), f"frame {index} must be an object")
        require(int(frame.get("frameID", -1)) == index, f"frame IDs are not contiguous at frame {index}")

        host_timestamp = int(frame.get("hostTimestampNanoseconds", -1))
        require(host_timestamp >= previous_host_timestamp, f"host timestamps regress at frame {index}")
        previous_host_timestamp = host_timestamp

        ar_timestamp = float(frame.get("arTimestampSeconds", float("nan")))
        require(math.isfinite(ar_timestamp), f"AR timestamp is non-finite at frame {index}")
        require(ar_timestamp >= previous_ar_timestamp, f"AR timestamps regress at frame {index}")
        previous_ar_timestamp = ar_timestamp

        require(frame.get("cameraTrackingState") == "normal", f"frame {index} was not captured with normal tracking")
        require(frame.get("nativeImageOrientation") == "landscapeRight", f"frame {index} orientation changed")
        require(frame.get("mirrored") is False, f"frame {index} is unexpectedly mirrored")
        validate_pose(frame.get("cameraToWorld"), f"frame {index} cameraToWorld")

        calibration = frame.get("calibration")
        require(isinstance(calibration, dict), f"frame {index} calibration is missing")
        image_width = int(calibration.get("imageWidth", 0))
        image_height = int(calibration.get("imageHeight", 0))
        depth_width = int(calibration.get("depthWidth", 0))
        depth_height = int(calibration.get("depthHeight", 0))
        require(min(image_width, image_height, depth_width, depth_height) > 0,
                f"frame {index} calibration dimensions are invalid")
        validate_intrinsics(calibration.get("imageIntrinsics"), f"frame {index} imageIntrinsics")
        validate_intrinsics(calibration.get("depthIntrinsics"), f"frame {index} depthIntrinsics")

        exposure = frame.get("exposure")
        require(isinstance(exposure, dict), f"frame {index} exposure metadata is missing")
        duration = float(exposure.get("durationSeconds", float("nan")))
        offset = float(exposure.get("exposureOffsetEV", float("nan")))
        require(math.isfinite(duration) and duration > 0.0, f"frame {index} exposure duration is invalid")
        require(math.isfinite(offset), f"frame {index} exposure offset is non-finite")

        referenced_files.append(validate_plane(
            capture, frame.get("luma"), label=f"frame {index} luma",
            expected_pixel_format="y8", expected_width=image_width, expected_height=image_height,
            seen_paths=seen_paths,
        ))
        referenced_files.append(validate_plane(
            capture, frame.get("chroma"), label=f"frame {index} chroma",
            expected_pixel_format="cbcr8x2", expected_width=None, expected_height=None,
            seen_paths=seen_paths,
        ))
        referenced_files.append(validate_plane(
            capture, frame.get("depth"), label=f"frame {index} depth",
            expected_pixel_format="depth-f32-metres", expected_width=depth_width, expected_height=depth_height,
            seen_paths=seen_paths,
        ))
        confidence = frame.get("confidence")
        if confidence is not None:
            confidence_frames += 1
            referenced_files.append(validate_plane(
                capture, confidence, label=f"frame {index} confidence",
                expected_pixel_format="arkit-confidence-u8", expected_width=depth_width, expected_height=depth_height,
                seen_paths=seen_paths,
            ))

    manifest_entry = {
        "path": "manifest.json",
        "bytes": manifest_path.stat().st_size,
        "sha256": sha256_file(manifest_path),
    }
    content_files = [manifest_entry, *referenced_files]

    expected_paths = {entry["path"] for entry in content_files}
    unexpected_files: list[str] = []
    for candidate in capture.rglob("*"):
        if candidate.is_symlink():
            raise ValueError(f"capture contains symlink: {candidate.relative_to(capture)}")
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(capture).as_posix()
        if relative == ".DS_Store":
            continue
        if relative not in expected_paths:
            unexpected_files.append(relative)
    require(not unexpected_files, f"capture contains unexpected files: {sorted(unexpected_files)}")

    recovery = manifest.get("recovery")
    if recovery is not None:
        require(isinstance(recovery, dict), "capture recovery metadata is invalid")
        require(int(recovery.get("journalFrames", -1)) == len(frames),
                "recovered journalFrames does not match frame count")
        require(int(recovery.get("discardedTrailingBytes", -1)) >= 0,
                "recovery discardedTrailingBytes is invalid")

    total_payload_bytes = sum(entry["bytes"] for entry in content_files)
    return {
        "schemaVersion": 1,
        "study": "reference-world-v1-acquisition",
        "stage": "C1.1-frozen-acquisition",
        "status": "frozen-valid-acquisition",
        "sceneName": scene_name,
        "ownershipReleaseStatement": ownership,
        "mavebCommit": maveb_commit,
        "capture": {
            "basename": capture.name,
            "manifestSchemaVersion": manifest["schemaVersion"],
            "sourceID": manifest["sourceID"],
            "createdAt": manifest.get("createdAt"),
            "completedAt": manifest.get("completedAt"),
            "application": application,
            "device": device,
            "coordinateSystem": coordinate_system,
            "frameCount": len(frames),
            "confidenceFrameCount": confidence_frames,
            "statistics": statistics,
            "recovery": recovery,
            "manifestSha256": manifest_entry["sha256"],
            "contentSetSha256": content_set_sha(content_files),
            "referencedFileCount": len(content_files),
            "totalReferencedBytes": total_payload_bytes,
        },
        "validationPolicy": {
            "minimumFrames": minimum_frames,
            "expectedManifestSchemaVersion": EXPECTED_MANIFEST_SCHEMA,
            "expectedApplication": {
                "name": EXPECTED_APP_NAME,
                "version": EXPECTED_APP_VERSION,
            },
        },
        "integrity": {
            "manifestFinalized": True,
            "journalAbsent": True,
            "checkpointAbsent": True,
            "frameIDsContiguous": True,
            "timestampsMonotonic": True,
            "normalTrackingOnly": True,
            "posesRigidCameraToWorld": True,
            "intrinsicsFinite": True,
            "allReferencedPlaneSizesVerified": True,
            "allReferencedPlaneHashesVerified": True,
            "unexpectedPayloadFilesAbsent": True,
            "syntheticFallbackUsed": False,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and freeze one finalized MavebCapture package as Reference World v1 acquisition evidence."
    )
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--scene-name", required=True)
    parser.add_argument("--ownership", required=True)
    parser.add_argument("--maveb-commit", required=True)
    parser.add_argument("--minimum-frames", type=int, default=30)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise ValueError(f"refusing to overwrite frozen acquisition evidence: {args.output}")
    evidence = build_evidence(
        args.capture,
        scene_name=args.scene_name,
        ownership=args.ownership,
        maveb_commit=args.maveb_commit,
        minimum_frames=args.minimum_frames,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
