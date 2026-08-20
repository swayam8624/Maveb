#!/usr/bin/env python3
"""Generate ARKitScenes depth-error samples for Maveb's metric-uncertainty study.

The input is a schema-v2 MavebCapture directory produced by `arkitscenes_to_aether.py` plus the
reference mesh in the same metric world frame. Each emitted JSONL row contains the observable
quantities consumed by `geometric_uncertainty.py` and a signed ground-truth depth error obtained by
ray casting the reference mesh.

Open3D is imported lazily so pure contract tests remain dependency-free. Run this script with
Maveb's pinned proxy Python environment for real-data experiments.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
from typing import Iterable, Iterator, Sequence


ARKIT_CONFIDENCE_MAX_LEVEL = 2


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def arkit_confidence_probability(raw: int) -> float:
    """Map ARConfidenceLevel raw values low/medium/high to 0/0.5/1.

    This is an ordinal research encoding, not a claim that ARKit's categories are calibrated
    probabilities. The distinction is recorded explicitly so U1 can test and later replace it.
    """

    if raw < 0 or raw > ARKIT_CONFIDENCE_MAX_LEVEL:
        raise ValueError(f"unknown ARKit confidence level: {raw}")
    return raw / ARKIT_CONFIDENCE_MAX_LEVEL


def image_aligned_ray_from_arkit_matrix(
    camera_to_world: Sequence[float],
    *,
    x: int,
    y: int,
    fx: float,
    fy: float,
    cx: float,
    cy: float,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Return world-space origin/direction with ray parameter equal to image-aligned camera Z.

    Schema-v2 stores a column-major native ARKit camera-to-world matrix (+Y up, -Z forward). Maveb's
    reconstruction convention is image-aligned +Y down, +Z forward, so columns 1 and 2 are negated.
    The direction is intentionally not normalized: Open3D RaycastingScene accepts non-normalized
    rays, and with camera-space direction [(x-cx)/fx, (y-cy)/fy, 1], `t_hit` is the depth along the
    image-aligned +Z axis rather than Euclidean range.
    """

    if len(camera_to_world) != 16:
        raise ValueError("cameraToWorld must contain 16 column-major values")
    values = [float(value) for value in camera_to_world]
    if any(not math.isfinite(value) for value in values):
        raise ValueError("cameraToWorld contains non-finite values")
    for name, value in (("fx", fx), ("fy", fy), ("cx", cx), ("cy", cy)):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
    if fx <= 0.0 or fy <= 0.0:
        raise ValueError("focal lengths must be positive")

    nx = (float(x) - cx) / fx
    ny = (float(y) - cy) / fy

    # Column-major native ARKit C2W. Convert image-aligned [nx, ny, 1] by applying
    # native [nx, -ny, -1].
    direction = (
        values[0] * nx - values[4] * ny - values[8],
        values[1] * nx - values[5] * ny - values[9],
        values[2] * nx - values[6] * ny - values[10],
    )
    origin = (values[12], values[13], values[14])
    return origin, direction


def read_float32_plane_value(
    data: bytes,
    *,
    x: int,
    y: int,
    width: int,
    height: int,
    row_stride_bytes: int,
) -> float:
    if not 0 <= x < width or not 0 <= y < height:
        raise ValueError("plane coordinate is outside dimensions")
    if row_stride_bytes < width * 4:
        raise ValueError("float32 row stride is too small")
    offset = y * row_stride_bytes + x * 4
    if offset + 4 > len(data):
        raise ValueError("float32 plane is truncated")
    return struct.unpack_from("<f", data, offset)[0]


def read_uint8_plane_value(
    data: bytes,
    *,
    x: int,
    y: int,
    width: int,
    height: int,
    row_stride_bytes: int,
) -> int:
    if not 0 <= x < width or not 0 <= y < height:
        raise ValueError("plane coordinate is outside dimensions")
    if row_stride_bytes < width:
        raise ValueError("uint8 row stride is too small")
    offset = y * row_stride_bytes + x
    if offset >= len(data):
        raise ValueError("uint8 plane is truncated")
    return data[offset]


def _read_verified_plane(root: Path, record: dict) -> bytes:
    path = root / record["path"]
    data = path.read_bytes()
    expected_count = int(record["byteCount"])
    if len(data) != expected_count:
        raise ValueError(f"plane byte count mismatch: {path}")
    digest = hashlib.sha256(data).hexdigest()
    if digest != record["sha256"]:
        raise ValueError(f"plane SHA-256 mismatch: {path}")
    return data


def _depth_intrinsics(frame: dict) -> tuple[float, float, float, float]:
    values = frame["calibration"]["depthIntrinsics"]
    if len(values) != 9:
        raise ValueError("depthIntrinsics must contain 9 column-major values")
    fx, fy, cx, cy = float(values[0]), float(values[4]), float(values[6]), float(values[7])
    if not all(math.isfinite(value) for value in (fx, fy, cx, cy)) or fx <= 0.0 or fy <= 0.0:
        raise ValueError("depth intrinsics are invalid")
    return fx, fy, cx, cy


def _candidate_rows(
    capture_root: Path,
    manifest: dict,
    *,
    scene: str,
    pixel_stride: int,
    frame_stride: int,
    maximum_depth_metres: float,
    pose_confidence: float,
    reprojection_error_pixels: float,
    alignment_position_rmse_metres: float,
    alignment_orientation_error_degrees: float,
) -> Iterator[tuple[dict, tuple[float, float, float], tuple[float, float, float]]]:
    frames = manifest["frames"]
    for frame_index in range(0, len(frames), frame_stride):
        frame = frames[frame_index]
        depth_record = frame["depth"]
        confidence_record = frame.get("confidence")
        if confidence_record is None:
            continue
        depth_bytes = _read_verified_plane(capture_root, depth_record)
        confidence_bytes = _read_verified_plane(capture_root, confidence_record)
        width = int(depth_record["width"])
        height = int(depth_record["height"])
        if int(confidence_record["width"]) != width or int(confidence_record["height"]) != height:
            raise ValueError("depth and confidence dimensions differ")
        fx, fy, cx, cy = _depth_intrinsics(frame)
        focal = math.sqrt(fx * fy)

        start = pixel_stride // 2
        for y in range(start, height, pixel_stride):
            for x in range(start, width, pixel_stride):
                depth = read_float32_plane_value(
                    depth_bytes,
                    x=x,
                    y=y,
                    width=width,
                    height=height,
                    row_stride_bytes=int(depth_record["rowStrideBytes"]),
                )
                if not math.isfinite(depth) or depth <= 0.0 or depth > maximum_depth_metres:
                    continue
                raw_confidence = read_uint8_plane_value(
                    confidence_bytes,
                    x=x,
                    y=y,
                    width=width,
                    height=height,
                    row_stride_bytes=int(confidence_record["rowStrideBytes"]),
                )
                sensor_confidence = arkit_confidence_probability(raw_confidence)
                origin, direction = image_aligned_ray_from_arkit_matrix(
                    frame["cameraToWorld"],
                    x=x,
                    y=y,
                    fx=fx,
                    fy=fy,
                    cx=cx,
                    cy=cy,
                )
                row = {
                    "scene": scene,
                    "sampleId": f"frame-{int(frame['frameID']):06d}-x{x}-y{y}",
                    "frameId": int(frame["frameID"]),
                    "pixelX": x,
                    "pixelY": y,
                    "depthMetres": depth,
                    "arkitConfidenceLevel": raw_confidence,
                    "sensorConfidence": sensor_confidence,
                    "poseConfidence": pose_confidence,
                    "reprojectionErrorPixels": reprojection_error_pixels,
                    "focalLengthPixels": focal,
                    "alignmentPositionRmseMetres": alignment_position_rmse_metres,
                    "alignmentOrientationErrorDegrees": alignment_orientation_error_degrees,
                }
                yield row, origin, direction


def generate_samples(
    capture_root: Path,
    reference_mesh: Path,
    output: Path,
    *,
    scene: str,
    pixel_stride: int = 8,
    frame_stride: int = 1,
    maximum_samples: int = 500_000,
    ray_batch_size: int = 65_536,
    maximum_depth_metres: float = 20.0,
    pose_confidence: float = 1.0,
    reprojection_error_pixels: float = 0.0,
    alignment_position_rmse_metres: float = 0.0,
    alignment_orientation_error_degrees: float = 0.0,
) -> dict:
    if pixel_stride <= 0 or frame_stride <= 0 or maximum_samples <= 0 or ray_batch_size <= 0:
        raise ValueError("stride, maximum-samples, and ray-batch-size must be positive")
    if not 0.0 <= pose_confidence <= 1.0:
        raise ValueError("pose confidence must be in [0, 1]")
    if maximum_depth_metres <= 0.0 or not math.isfinite(maximum_depth_metres):
        raise ValueError("maximum depth must be finite and positive")

    manifest_path = capture_root / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("schemaVersion") != 2:
        raise ValueError("ARKit uncertainty sampling requires schema-v2 capture input")
    if not isinstance(manifest.get("frames"), list) or not manifest["frames"]:
        raise ValueError("capture manifest contains no frames")

    try:
        import numpy as np
        import open3d as o3d
    except ImportError as exc:
        raise RuntimeError(
            "ARKit uncertainty sampling requires NumPy and Open3D; run with proxy-python"
        ) from exc

    legacy_mesh = o3d.io.read_triangle_mesh(str(reference_mesh))
    if legacy_mesh.is_empty() or len(legacy_mesh.triangles) == 0:
        raise ValueError(f"reference mesh is empty or unreadable: {reference_mesh}")
    mesh = o3d.t.geometry.TriangleMesh.from_legacy(legacy_mesh)
    ray_scene = o3d.t.geometry.RaycastingScene()
    ray_scene.add_triangles(mesh)

    output.parent.mkdir(parents=True, exist_ok=True)
    emitted = 0
    misses = 0
    candidates = 0
    batch_rows: list[dict] = []
    batch_rays: list[tuple[float, float, float, float, float, float]] = []

    def flush(stream) -> None:
        nonlocal emitted, misses
        if not batch_rows:
            return
        rays = o3d.core.Tensor(np.asarray(batch_rays, dtype=np.float32))
        hits = ray_scene.cast_rays(rays)["t_hit"].numpy()
        for row, hit in zip(batch_rows, hits):
            hit_depth = float(hit)
            if not math.isfinite(hit_depth) or hit_depth <= 0.0:
                misses += 1
                continue
            result = dict(row)
            result["referenceDepthMetres"] = hit_depth
            result["signedErrorMetres"] = result["depthMetres"] - hit_depth
            stream.write(json.dumps(result, sort_keys=True) + "\n")
            emitted += 1
            if emitted >= maximum_samples:
                break
        batch_rows.clear()
        batch_rays.clear()

    with output.open("w", encoding="utf-8") as stream:
        for row, origin, direction in _candidate_rows(
            capture_root,
            manifest,
            scene=scene,
            pixel_stride=pixel_stride,
            frame_stride=frame_stride,
            maximum_depth_metres=maximum_depth_metres,
            pose_confidence=pose_confidence,
            reprojection_error_pixels=reprojection_error_pixels,
            alignment_position_rmse_metres=alignment_position_rmse_metres,
            alignment_orientation_error_degrees=alignment_orientation_error_degrees,
        ):
            candidates += 1
            batch_rows.append(row)
            batch_rays.append((*origin, *direction))
            if len(batch_rows) >= ray_batch_size:
                flush(stream)
                if emitted >= maximum_samples:
                    break
        if emitted < maximum_samples:
            flush(stream)

    metadata = {
        "schemaVersion": 1,
        "scene": scene,
        "captureManifest": str(manifest_path.resolve()),
        "captureManifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "referenceMesh": str(reference_mesh.resolve()),
        "referenceMeshSha256": sha256_file(reference_mesh),
        "output": str(output.resolve()),
        "outputSha256": sha256_file(output),
        "candidateSamples": candidates,
        "emittedSamples": emitted,
        "referenceMisses": misses,
        "pixelStride": pixel_stride,
        "frameStride": frame_stride,
        "maximumSamples": maximum_samples,
        "rayBatchSize": ray_batch_size,
        "maximumDepthMetres": maximum_depth_metres,
        "poseConfidence": pose_confidence,
        "reprojectionErrorPixels": reprojection_error_pixels,
        "alignmentPositionRmseMetres": alignment_position_rmse_metres,
        "alignmentOrientationErrorDegrees": alignment_orientation_error_degrees,
        "confidenceEncoding": {
            "source": "ARConfidenceLevel raw ordinal",
            "researchMapping": {"0": 0.0, "1": 0.5, "2": 1.0},
            "claim": "ordinal research encoding; not a calibrated probability",
        },
        "rayConvention": (
            "schema-v2 native ARKit C2W converted to image-aligned +Y-down/+Z-forward; "
            "non-normalized ray parameter equals camera Z depth"
        ),
    }
    metadata_path = output.with_suffix(output.suffix + ".meta.json")
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("reference_mesh", type=Path)
    parser.add_argument("--scene", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pixel-stride", type=int, default=8)
    parser.add_argument("--frame-stride", type=int, default=1)
    parser.add_argument("--max-samples", type=int, default=500_000)
    parser.add_argument("--ray-batch-size", type=int, default=65_536)
    parser.add_argument("--max-depth", type=float, default=20.0)
    parser.add_argument("--pose-confidence", type=float, default=1.0)
    parser.add_argument("--reprojection-error-pixels", type=float, default=0.0)
    parser.add_argument("--alignment-position-rmse", type=float, default=0.0)
    parser.add_argument("--alignment-orientation-error-degrees", type=float, default=0.0)
    args = parser.parse_args()

    try:
        metadata = generate_samples(
            args.capture.resolve(),
            args.reference_mesh.resolve(),
            args.output.resolve(),
            scene=args.scene,
            pixel_stride=args.pixel_stride,
            frame_stride=args.frame_stride,
            maximum_samples=args.max_samples,
            ray_batch_size=args.ray_batch_size,
            maximum_depth_metres=args.max_depth,
            pose_confidence=args.pose_confidence,
            reprojection_error_pixels=args.reprojection_error_pixels,
            alignment_position_rmse_metres=args.alignment_position_rmse,
            alignment_orientation_error_degrees=args.alignment_orientation_error_degrees,
        )
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"arkit_uncertainty_samples: {exc}")
        return 2
    print(json.dumps({"ok": True, **metadata}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
