#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

# C1.2 is a pre-reconstruction engineering sanity gate. These thresholds are
# frozen in source before Reference World v1 depth statistics are inspected.
MIN_GLOBAL_POSITIVE_DEPTH_FRACTION = 0.20
MIN_PER_FRAME_POSITIVE_DEPTH_FRACTION = 0.10
MAX_EXTREME_DEPTH_METRES = 20.0
MAX_EXTREME_DEPTH_FRACTION = 0.001
MIN_GLOBAL_CONFIDENT_FRACTION = 0.20
MIN_PER_FRAME_CONFIDENT_FRACTION = 0.10
MIN_CAMERA_TRANSLATION_EXTENT_METRES = 0.15
MIN_CAMERA_PATH_LENGTH_METRES = 0.50

AUTO_BOUNDS_MAX_AXIS = 256
AUTO_BOUNDS_SAMPLE_STRIDE = 8
AUTO_BOUNDS_PADDING_METRES = 0.10
FUSION_VOXEL_METRES = 0.01
FUSION_TRUNCATION_METRES = 0.04

DEPTH_EDGES = (0.10, 0.25, 0.50, 1.0, 2.0, 4.0, 8.0, 20.0)
DEPTH_LABELS = (
    "(0,0.10)",
    "[0.10,0.25)",
    "[0.25,0.50)",
    "[0.50,1.0)",
    "[1.0,2.0)",
    "[2.0,4.0)",
    "[4.0,8.0)",
    "[8.0,20.0)",
    "[20.0,+inf)",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    require(path.is_file(), f"{label} is missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{label} must be a JSON object")
    return value


def finite(value: Any, label: str) -> float:
    number = float(value)
    require(math.isfinite(number), f"{label} is non-finite")
    return number


def percentile(values: list[float], fraction: float) -> float:
    require(bool(values), "cannot compute percentile of empty values")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def capture_file(root: Path, relative_path: str) -> Path:
    relative = Path(relative_path)
    require(relative_path != "", "capture plane path is empty")
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


def plane_layout(plane: Any, expected_format: str, label: str) -> tuple[str, int, int, int]:
    require(isinstance(plane, dict), f"{label} must be an object")
    require(plane.get("pixelFormat") == expected_format, f"{label} pixel format changed")
    relative_path = str(plane.get("path", ""))
    width = int(plane.get("width", 0))
    height = int(plane.get("height", 0))
    stride = int(plane.get("rowStrideBytes", 0))
    require(width > 0 and height > 0 and stride > 0, f"{label} dimensions/stride are invalid")
    bytes_per_pixel = 4 if expected_format == "depth-f32-metres" else 1
    require(stride >= width * bytes_per_pixel, f"{label} row stride is too small")
    return relative_path, width, height, stride


def read_depth_frame(path: Path, width: int, height: int, stride: int) -> list[float]:
    values: list[float] = []
    active_bytes = width * 4
    with path.open("rb") as handle:
        for row_index in range(height):
            row = handle.read(stride)
            require(len(row) == stride, f"short depth row {row_index} in {path}")
            values.extend(item[0] for item in struct.iter_unpack("<f", row[:active_bytes]))
        require(handle.read(1) == b"", f"depth file exceeds declared stride/height: {path}")
    return values


def read_confidence_frame(path: Path, width: int, height: int, stride: int) -> bytes:
    values = bytearray()
    with path.open("rb") as handle:
        for row_index in range(height):
            row = handle.read(stride)
            require(len(row) == stride, f"short confidence row {row_index} in {path}")
            values.extend(row[:width])
        require(handle.read(1) == b"", f"confidence file exceeds declared stride/height: {path}")
    return bytes(values)


def depth_histogram_index(value: float) -> int:
    for index, edge in enumerate(DEPTH_EDGES):
        if value < edge:
            return index
    return len(DEPTH_EDGES)


def camera_position(frame: dict[str, Any], index: int) -> tuple[float, float, float]:
    matrix = frame.get("cameraToWorld")
    require(isinstance(matrix, list) and len(matrix) == 16, f"frame {index} cameraToWorld must contain 16 values")
    values = [finite(value, f"frame {index} cameraToWorld") for value in matrix]
    return values[12], values[13], values[14]


def run_fusion_dry_run(executable: Path, capture: Path) -> dict[str, Any]:
    executable = executable.resolve()
    require(executable.is_file(), f"aether-fuse executable is missing: {executable}")
    require(os.access(executable, os.X_OK), f"aether-fuse is not executable: {executable}")
    arguments = [
        "--auto-bounds",
        "--max-axis", str(AUTO_BOUNDS_MAX_AXIS),
        "--sample-stride", str(AUTO_BOUNDS_SAMPLE_STRIDE),
        "--padding", str(AUTO_BOUNDS_PADDING_METRES),
        "--voxel", str(FUSION_VOXEL_METRES),
        "--truncation", str(FUSION_TRUNCATION_METRES),
        "--dry-run",
        "--json",
    ]
    completed = subprocess.run(
        [str(executable), str(capture), *arguments],
        text=True,
        capture_output=True,
        check=False,
    )
    require(
        completed.returncode == 0,
        "aether-fuse dry-run failed: "
        + (completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"),
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    require(bool(lines), "aether-fuse dry-run produced no JSON")
    payload = json.loads(lines[-1])
    require(isinstance(payload, dict), "aether-fuse dry-run result must be a JSON object")
    require(payload.get("ok") is True and payload.get("dryRun") is True, "aether-fuse dry-run did not report success")
    require(payload.get("automaticBounds") is True, "aether-fuse dry-run did not use automatic bounds")
    require(int(payload.get("sampledPoints", 0)) > 0, "aether-fuse automatic bounds sampled no points")
    dimensions = payload.get("dimensions")
    require(
        isinstance(dimensions, list)
        and len(dimensions) == 3
        and all(0 < int(value) <= AUTO_BOUNDS_MAX_AXIS for value in dimensions),
        "aether-fuse automatic bounds dimensions are invalid",
    )
    origin = payload.get("origin")
    require(
        isinstance(origin, list)
        and len(origin) == 3
        and all(math.isfinite(float(value)) for value in origin),
        "aether-fuse automatic bounds origin is invalid",
    )
    voxel = finite(payload.get("voxelSizeMetres"), "aether-fuse voxelSizeMetres")
    truncation = finite(payload.get("truncationDistanceMetres"), "aether-fuse truncationDistanceMetres")
    require(voxel >= FUSION_VOXEL_METRES, "aether-fuse returned an invalid voxel size")
    expected_truncation = max(4.0 * voxel, FUSION_TRUNCATION_METRES)
    require(
        math.isclose(
            truncation,
            expected_truncation,
            rel_tol=1e-5,
            abs_tol=1e-7,
        ),
        "aether-fuse truncation distance does not match automatic-bounds contract",
    )
    payload["command"] = ["aether-fuse", "<frozen-reference.mavebcapture>", *arguments]
    return payload


def build_validation(
    capture: Path,
    acquisition_evidence_path: Path,
    aether_fuse: Path,
    validation_commit: str,
) -> dict[str, Any]:
    capture = capture.resolve()
    require(capture.is_dir() and capture.suffix == ".mavebcapture", "capture must be a .mavebcapture directory")
    validation_commit = validation_commit.strip().lower()
    require(bool(HEX40.fullmatch(validation_commit)), "validation commit must be a full lowercase 40-character SHA")

    acquisition = load_json(acquisition_evidence_path, "acquisition evidence")
    require(acquisition.get("status") == "frozen-valid-acquisition", "acquisition evidence is not frozen-valid")
    frozen_capture = acquisition.get("capture")
    require(isinstance(frozen_capture, dict), "acquisition evidence capture section is missing")

    manifest_path = capture / "manifest.json"
    manifest = load_json(manifest_path, "capture manifest")
    manifest_sha = sha256_file(manifest_path)
    expected_manifest_sha = str(frozen_capture.get("manifestSha256", ""))
    require(bool(HEX64.fullmatch(expected_manifest_sha)), "frozen manifest SHA-256 is invalid")
    require(manifest_sha == expected_manifest_sha, "capture manifest no longer matches frozen acquisition evidence")

    frames = manifest.get("frames")
    require(isinstance(frames, list) and bool(frames), "capture manifest contains no frames")
    require(len(frames) == int(frozen_capture.get("frameCount", -1)), "capture frame count changed after freeze")

    depth_total = depth_positive = depth_zero = depth_negative = depth_nonfinite = depth_extreme = 0
    depth_sum = 0.0
    depth_min = math.inf
    depth_max = -math.inf
    depth_histogram = [0] * len(DEPTH_LABELS)
    sampled_depths: list[float] = []
    per_frame_positive: list[float] = []

    confidence_total = illegal_confidence = 0
    confidence_histogram = [0, 0, 0]
    per_frame_confident: list[float] = []
    positions: list[tuple[float, float, float]] = []

    for index, frame in enumerate(frames, start=1):
        require(isinstance(frame, dict), f"frame {index} must be an object")
        positions.append(camera_position(frame, index))

        depth_rel, width, height, stride = plane_layout(frame.get("depth"), "depth-f32-metres", f"frame {index} depth")
        depth_values = read_depth_frame(capture_file(capture, depth_rel), width, height, stride)
        frame_positive = 0
        positive_seen = 0
        for value in depth_values:
            depth_total += 1
            if not math.isfinite(value):
                depth_nonfinite += 1
            elif value < 0.0:
                depth_negative += 1
            elif value == 0.0:
                depth_zero += 1
            else:
                depth_positive += 1
                frame_positive += 1
                depth_sum += value
                depth_min = min(depth_min, value)
                depth_max = max(depth_max, value)
                depth_histogram[depth_histogram_index(value)] += 1
                if value >= MAX_EXTREME_DEPTH_METRES:
                    depth_extreme += 1
                if positive_seen % 64 == 0:
                    sampled_depths.append(value)
                positive_seen += 1
        per_frame_positive.append(frame_positive / len(depth_values))

        confidence = frame.get("confidence")
        require(confidence is not None, f"frame {index} has no confidence plane")
        conf_rel, conf_width, conf_height, conf_stride = plane_layout(
            confidence, "arkit-confidence-u8", f"frame {index} confidence"
        )
        require(conf_width == width and conf_height == height, f"frame {index} confidence dimensions differ from depth")
        confidence_values = read_confidence_frame(capture_file(capture, conf_rel), conf_width, conf_height, conf_stride)
        require(len(confidence_values) == len(depth_values), f"frame {index} confidence/depth pixel counts differ")
        frame_confident = 0
        for value in confidence_values:
            confidence_total += 1
            if value <= 2:
                confidence_histogram[value] += 1
                if value >= 1:
                    frame_confident += 1
            else:
                illegal_confidence += 1
        per_frame_confident.append(frame_confident / len(confidence_values))

    require(depth_total > 0 and depth_positive > 0, "capture contains no positive finite metric depth")
    positive_fraction = depth_positive / depth_total
    extreme_fraction = depth_extreme / depth_positive
    require(depth_negative == 0, f"capture contains {depth_negative} negative metric depth samples")
    require(
        positive_fraction >= MIN_GLOBAL_POSITIVE_DEPTH_FRACTION,
        f"positive finite depth fraction {positive_fraction:.6f} is below frozen gate {MIN_GLOBAL_POSITIVE_DEPTH_FRACTION:.6f}",
    )
    require(
        min(per_frame_positive) >= MIN_PER_FRAME_POSITIVE_DEPTH_FRACTION,
        f"a frame's positive finite depth fraction is below frozen gate {MIN_PER_FRAME_POSITIVE_DEPTH_FRACTION:.6f}",
    )
    require(
        extreme_fraction <= MAX_EXTREME_DEPTH_FRACTION,
        f"depth >= {MAX_EXTREME_DEPTH_METRES:g} m fraction {extreme_fraction:.6f} exceeds frozen gate {MAX_EXTREME_DEPTH_FRACTION:.6f}",
    )

    require(confidence_total == depth_total, "global confidence/depth pixel counts differ")
    require(illegal_confidence == 0, f"capture contains {illegal_confidence} illegal ARKit confidence codes")
    confident_fraction = (confidence_histogram[1] + confidence_histogram[2]) / confidence_total
    require(
        confident_fraction >= MIN_GLOBAL_CONFIDENT_FRACTION,
        f"confidence >=1 fraction {confident_fraction:.6f} is below frozen gate {MIN_GLOBAL_CONFIDENT_FRACTION:.6f}",
    )
    require(
        min(per_frame_confident) >= MIN_PER_FRAME_CONFIDENT_FRACTION,
        f"a frame's confidence >=1 fraction is below frozen gate {MIN_PER_FRAME_CONFIDENT_FRACTION:.6f}",
    )

    axis_extents = [max(values) - min(values) for values in zip(*positions)]
    translation_extent = math.sqrt(sum(value * value for value in axis_extents))
    path_length = 0.0
    max_step = 0.0
    for left, right in zip(positions, positions[1:]):
        step = math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))
        path_length += step
        max_step = max(max_step, step)
    require(
        translation_extent >= MIN_CAMERA_TRANSLATION_EXTENT_METRES,
        f"camera translation extent {translation_extent:.6f} m is below frozen gate {MIN_CAMERA_TRANSLATION_EXTENT_METRES:.6f} m",
    )
    require(
        path_length >= MIN_CAMERA_PATH_LENGTH_METRES,
        f"camera path length {path_length:.6f} m is below frozen gate {MIN_CAMERA_PATH_LENGTH_METRES:.6f} m",
    )

    dry_run = run_fusion_dry_run(aether_fuse, capture)
    require(int(dry_run.get("frames", -1)) == len(frames), "aether-fuse dry-run frame count differs from frozen capture")

    return {
        "schemaVersion": 1,
        "study": "reference-world-v1-capture-validation",
        "stage": "C1.2-capture-validation",
        "status": "validated-geometry-usable",
        "validationCommit": validation_commit,
        "acquisition": {
            "evidencePath": acquisition_evidence_path.as_posix(),
            "evidenceSha256": sha256_file(acquisition_evidence_path),
            "mavebCommit": acquisition.get("mavebCommit"),
            "manifestSha256": manifest_sha,
            "contentSetSha256": frozen_capture.get("contentSetSha256"),
            "sourceID": frozen_capture.get("sourceID"),
            "frameCount": len(frames),
        },
        "depth": {
            "unit": "metres",
            "pixelCount": depth_total,
            "positiveFiniteCount": depth_positive,
            "positiveFiniteFraction": positive_fraction,
            "zeroCount": depth_zero,
            "negativeFiniteCount": depth_negative,
            "nonFiniteCount": depth_nonfinite,
            "extremeAtOrAbove20mCount": depth_extreme,
            "extremeAtOrAbove20mFractionOfPositive": extreme_fraction,
            "minimumPositiveMetres": depth_min,
            "maximumPositiveMetres": depth_max,
            "meanPositiveMetres": depth_sum / depth_positive,
            "sampledQuantiles": {
                "count": len(sampled_depths),
                "samplingRule": "every 64th positive finite depth sample independently within each frame",
                "p01Metres": percentile(sampled_depths, 0.01),
                "p10Metres": percentile(sampled_depths, 0.10),
                "p50Metres": percentile(sampled_depths, 0.50),
                "p90Metres": percentile(sampled_depths, 0.90),
                "p99Metres": percentile(sampled_depths, 0.99),
            },
            "histogramPositiveDepth": dict(zip(DEPTH_LABELS, depth_histogram)),
            "perFramePositiveFraction": {
                "minimum": min(per_frame_positive),
                "median": percentile(per_frame_positive, 0.50),
                "maximum": max(per_frame_positive),
            },
        },
        "confidence": {
            "pixelCount": confidence_total,
            "legalCodes": [0, 1, 2],
            "histogram": {
                "0-low": confidence_histogram[0],
                "1-medium": confidence_histogram[1],
                "2-high": confidence_histogram[2],
            },
            "illegalCodeCount": illegal_confidence,
            "atLeastMediumFraction": confident_fraction,
            "perFrameAtLeastMediumFraction": {
                "minimum": min(per_frame_confident),
                "median": percentile(per_frame_confident, 0.50),
                "maximum": max(per_frame_confident),
            },
        },
        "cameraMotion": {
            "axisExtentsMetres": axis_extents,
            "translationExtentMetres": translation_extent,
            "pathLengthMetres": path_length,
            "maximumConsecutiveStepMetres": max_step,
        },
        "fusionDryRun": dry_run,
        "validationPolicy": {
            "minimumGlobalPositiveDepthFraction": MIN_GLOBAL_POSITIVE_DEPTH_FRACTION,
            "minimumPerFramePositiveDepthFraction": MIN_PER_FRAME_POSITIVE_DEPTH_FRACTION,
            "maximumExtremeDepthMetres": MAX_EXTREME_DEPTH_METRES,
            "maximumExtremeDepthFractionOfPositive": MAX_EXTREME_DEPTH_FRACTION,
            "minimumGlobalConfidenceAtLeastMediumFraction": MIN_GLOBAL_CONFIDENT_FRACTION,
            "minimumPerFrameConfidenceAtLeastMediumFraction": MIN_PER_FRAME_CONFIDENT_FRACTION,
            "minimumCameraTranslationExtentMetres": MIN_CAMERA_TRANSLATION_EXTENT_METRES,
            "minimumCameraPathLengthMetres": MIN_CAMERA_PATH_LENGTH_METRES,
            "aetherFuseAutoBounds": {
                "maximumAxisVoxels": AUTO_BOUNDS_MAX_AXIS,
                "sampleStridePixels": AUTO_BOUNDS_SAMPLE_STRIDE,
                "paddingMetres": AUTO_BOUNDS_PADDING_METRES,
                "minimumVoxelMetres": FUSION_VOXEL_METRES,
                "minimumTruncationMetres": FUSION_TRUNCATION_METRES,
                "effectiveTruncationRule": "max(4 * effectiveVoxelMetres, minimumTruncationMetres)",
            },
        },
        "integrity": {
            "frozenAcquisitionManifestMatched": True,
            "allDepthPlanesRead": True,
            "allConfidencePlanesRead": True,
            "negativeMetricDepthAbsent": True,
            "confidenceCodesLegal": True,
            "fusionMaintainedPathDryRunPassed": True,
            "reconstructionIntegrated": False,
            "syntheticFallbackUsed": False,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate frozen Reference World v1 RGB-D numerics before any reconstruction."
    )
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--acquisition-evidence", type=Path, required=True)
    parser.add_argument("--aether-fuse", type=Path, required=True)
    parser.add_argument("--validation-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        require(not args.output.exists(), f"refusing to overwrite existing validation evidence: {args.output}")
        evidence = build_validation(
            args.capture,
            args.acquisition_evidence,
            args.aether_fuse,
            args.validation_commit,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(evidence, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(f"reference-world-v1 capture validation failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
