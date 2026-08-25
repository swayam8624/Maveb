#!/usr/bin/env python3
"""Prepare one frozen CA-1M U3 scene for Maveb's dense CPU TSDF experiment.

The adapter deliberately avoids RecordedSequenceSource because CA-1M already uses
image-aligned +X right, +Y down, +Z forward camera coordinates and has per-frame
intrinsics. It writes a tiny research manifest consumed directly by maveb-u3-fuse.

No FARO residual is used for frame selection, confidence filtering, bounds, or
fusion. FARO depth is used only to build the frozen reference point cloud.
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
from pathlib import Path
import sys
import tarfile

import numpy as np

from ca1m_u3_pose_preflight import (
    decode_depth,
    discover_frames,
    parse_intrinsics,
    parse_pose,
    read_member,
)
from ca1m_uncertainty_samples import (
    apply_discrete_transform,
    discover_sidecar_frames,
    infer_orientation_transform,
    nearest_sidecar_frame,
)


MM_TO_M = 1000.0
FROZEN_MODEL_SHA256 = "744cdfce9763f5d2ecd9c9a4e53385f66d8bba7cbc047e11729189053a85e17a"
SIDE_CAR_MAX_DELTA_SECONDS = 0.020


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def video_id_from_archive(path: Path) -> str:
    video_id = path.stem.rsplit("-", 1)[-1]
    if not video_id.isdigit():
        raise ValueError(f"unable to infer video id from {path.name}")
    return video_id


def matrix_to_quaternion_wxyz(rotation: np.ndarray) -> list[float]:
    if rotation.shape != (3, 3):
        raise ValueError("rotation must be 3x3")
    trace = float(np.trace(rotation))
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * scale
        x = (rotation[2, 1] - rotation[1, 2]) / scale
        y = (rotation[0, 2] - rotation[2, 0]) / scale
        z = (rotation[1, 0] - rotation[0, 1]) / scale
    elif rotation[0, 0] > rotation[1, 1] and rotation[0, 0] > rotation[2, 2]:
        scale = math.sqrt(1.0 + rotation[0, 0] - rotation[1, 1] - rotation[2, 2]) * 2.0
        w = (rotation[2, 1] - rotation[1, 2]) / scale
        x = 0.25 * scale
        y = (rotation[0, 1] + rotation[1, 0]) / scale
        z = (rotation[0, 2] + rotation[2, 0]) / scale
    elif rotation[1, 1] > rotation[2, 2]:
        scale = math.sqrt(1.0 + rotation[1, 1] - rotation[0, 0] - rotation[2, 2]) * 2.0
        w = (rotation[0, 2] - rotation[2, 0]) / scale
        x = (rotation[0, 1] + rotation[1, 0]) / scale
        y = 0.25 * scale
        z = (rotation[1, 2] + rotation[2, 1]) / scale
    else:
        scale = math.sqrt(1.0 + rotation[2, 2] - rotation[0, 0] - rotation[1, 1]) * 2.0
        w = (rotation[1, 0] - rotation[0, 1]) / scale
        x = (rotation[0, 2] + rotation[2, 0]) / scale
        y = (rotation[1, 2] + rotation[2, 1]) / scale
        z = 0.25 * scale
    quaternion = np.asarray([w, x, y, z], dtype=np.float64)
    norm = float(np.linalg.norm(quaternion))
    if not math.isfinite(norm) or norm <= 0.0:
        raise ValueError("pose produced an invalid quaternion")
    quaternion /= norm
    return [float(value) for value in quaternion]


def backproject_world(depth: np.ndarray, intrinsics: tuple[float, float, float, float], pose: np.ndarray,
                      pixel_stride: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    height, width = depth.shape
    start = pixel_stride // 2
    ys = np.arange(start, height, pixel_stride, dtype=np.int64)
    xs = np.arange(start, width, pixel_stride, dtype=np.int64)
    grid_x, grid_y = np.meshgrid(xs, ys)
    z = depth[grid_y, grid_x]
    valid = np.isfinite(z) & (z >= 0.05) & (z <= 20.0)
    grid_x = grid_x[valid]
    grid_y = grid_y[valid]
    z = z[valid]
    fx, fy, cx, cy = intrinsics
    camera = np.stack(
        ((grid_x.astype(np.float64) - cx) * z / fx,
         (grid_y.astype(np.float64) - cy) * z / fy,
         z),
        axis=1,
    )
    world = camera @ pose[:3, :3].T + pose[:3, 3]
    return world, grid_x, grid_y


def dense_bounds(selected: list[dict], *, pixel_stride: int, lower_quantile: float,
                 upper_quantile: float, padding: float, minimum_voxel: float,
                 maximum_axis_voxels: int) -> dict:
    coordinates = [[], [], []]
    for record in selected:
        world, _, _ = backproject_world(record["depth"], record["intrinsics"], record["pose"], pixel_stride)
        for axis in range(3):
            coordinates[axis].append(world[:, axis])
    merged = [np.concatenate(axis) for axis in coordinates]
    if len(merged[0]) < 8:
        raise ValueError("too few selected-view depth samples to estimate U3 bounds")
    observed_minimum: list[float] = []
    observed_maximum: list[float] = []
    origin: list[float] = []
    padded_maximum: list[float] = []
    for values in merged:
        values.sort()
        lower_index = min(len(values) - 1, int(lower_quantile * (len(values) - 1)))
        upper_index = min(len(values) - 1, int(upper_quantile * (len(values) - 1)))
        low = float(values[lower_index])
        high = float(values[upper_index])
        observed_minimum.append(low)
        observed_maximum.append(high)
        origin.append(low - padding)
        padded_maximum.append(high + padding)
    voxel = minimum_voxel
    for axis in range(3):
        span = padded_maximum[axis] - origin[axis]
        if not math.isfinite(span) or span <= 0.0:
            raise ValueError("U3 bounds are degenerate")
        voxel = max(voxel, span / (maximum_axis_voxels - 1))
    dimensions = []
    for axis in range(3):
        span = padded_maximum[axis] - origin[axis]
        dimensions.append(int(np.clip(math.ceil(span / voxel) + 1, 2, maximum_axis_voxels)))
    return {
        "sampledPoints": int(len(merged[0])),
        "observedMinimumMetres": observed_minimum,
        "observedMaximumMetres": observed_maximum,
        "originMetres": origin,
        "dimensions": dimensions,
        "voxelSizeMetres": float(voxel),
        "truncationDistanceMetres": float(max(4.0 * voxel, 0.04)),
        "minimumDepthMetres": 0.05,
        "maximumDepthMetres": 20.0,
        "maximumWeight": 100.0,
    }


def splitmix64(values: np.ndarray) -> np.ndarray:
    mask = np.uint64(0xFFFFFFFFFFFFFFFF)
    z = (values + np.uint64(0x9E3779B97F4A7C15)) & mask
    z = ((z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)) & mask
    z = ((z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)) & mask
    return z ^ (z >> np.uint64(31))


def shuffled_confidence(frames: list[np.ndarray], seed: int) -> list[np.ndarray]:
    lengths = [int(frame.size) for frame in frames]
    flat = np.concatenate([frame.reshape(-1) for frame in frames])
    indices = np.arange(flat.size, dtype=np.uint64)
    keys = splitmix64(indices ^ np.uint64(seed))
    order = np.argsort(keys, kind="stable")
    shuffled = np.empty_like(flat)
    shuffled[order] = flat
    result = []
    offset = 0
    for frame, length in zip(frames, lengths):
        result.append(shuffled[offset : offset + length].reshape(frame.shape))
        offset += length
    return result


def write_binary_ply(path: Path, points: list[tuple[float, float, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        f"element vertex {len(points)}\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "end_header\n"
    ).encode("ascii")
    array = np.asarray(points, dtype="<f4")
    with path.open("wb") as stream:
        stream.write(header)
        stream.write(array.tobytes(order="C"))


def build_reference(archive: tarfile.TarFile, frames, *, scene: str, pixel_stride: int,
                    maximum_points: int) -> tuple[list[tuple[float, float, float]], int]:
    heap: list[tuple[int, int, int, int, tuple[float, float, float]]] = []
    candidate_count = 0
    progress_step = max(1, len(frames) // 10)
    for frame_index, frame in enumerate(frames):
        depth = decode_depth(read_member(archive, frame.members["gt/depth"]))
        intrinsics = parse_intrinsics(read_member(archive, frame.members["gt/depth/k"]))
        pose = parse_pose(read_member(archive, frame.members["gt/rt"]))
        world, xs, ys = backproject_world(depth, intrinsics, pose, pixel_stride)
        timestamp = int(frame.timestamp)
        for point, x, y in zip(world, xs, ys):
            identity = f"{scene}/{timestamp}/x{int(x)}/y{int(y)}".encode("ascii")
            rank = int.from_bytes(hashlib.sha256(identity).digest(), "big")
            record = (-rank, timestamp, int(y), int(x), (float(point[0]), float(point[1]), float(point[2])))
            candidate_count += 1
            if len(heap) < maximum_points:
                heapq.heappush(heap, record)
            elif rank < -heap[0][0]:
                heapq.heapreplace(heap, record)
        if (frame_index + 1) % progress_step == 0 or frame_index + 1 == len(frames):
            print(
                json.dumps({
                    "u3ReferenceProgress": {
                        "scene": scene,
                        "framesProcessed": frame_index + 1,
                        "framesTotal": len(frames),
                        "candidatePoints": candidate_count,
                        "retainedPoints": len(heap),
                    }
                }),
                file=sys.stderr,
                flush=True,
            )
    retained = [record[4] for record in sorted(heap, key=lambda item: (-item[0], item[1], item[2], item[3]))]
    return retained, candidate_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--confidence-root", type=Path, required=True)
    parser.add_argument("--lowres-depth-root", type=Path, required=True)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--pose-gate", type=Path, required=True)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    video_id = video_id_from_archive(args.archive)
    scene = f"ca1m-{video_id}"
    for path in (args.archive, args.preflight, args.pose_gate, args.study, args.model):
        if not path.is_file():
            raise FileNotFoundError(path)
    if sha256_file(args.model) != FROZEN_MODEL_SHA256:
        raise ValueError("U3 requires the exact frozen U1b model SHA")

    study = json.loads(args.study.read_text())
    if study.get("id") != "metric-uncertainty-u3-dense-tsdf-v1" or not study.get("frozen"):
        raise ValueError("U3 study manifest is not the frozen dense-TSDF experiment")
    if study["frozenUncertaintyModel"]["sha256"] != FROZEN_MODEL_SHA256:
        raise ValueError("U3 study manifest references a different uncertainty model")
    if scene not in study["evaluationScenes"]:
        raise ValueError(f"scene {scene} is not in the frozen U3 evaluation set")

    preflight = json.loads(args.preflight.read_text())
    gate = json.loads(args.pose_gate.read_text())
    if gate.get("status") != "passed" or gate.get("inputPreflightSha256") != sha256_file(args.preflight):
        raise ValueError("corrected U3 pose gate does not authorize this preflight artifact")
    gate_scene = next((item for item in gate["scenes"] if item["videoId"] == video_id), None)
    if not gate_scene or not gate_scene.get("frozenManifestRulePassed"):
        raise ValueError(f"pose convention did not pass the frozen rule for {video_id}")
    preflight_scene = next((item for item in preflight["scenes"] if item["videoId"] == video_id), None)
    if not preflight_scene:
        raise ValueError(f"preflight does not contain scene {video_id}")
    selected_timestamps = [str(item["timestampNanoseconds"]) for item in preflight_scene["primaryEightViewSelection"]]
    if len(selected_timestamps) != study["primaryComparison"]["viewCount"]:
        raise ValueError("preflight primary-view selection does not match frozen U3 view count")

    confidence_frames = discover_sidecar_frames(args.confidence_root, video_id, "confidence")
    witness_frames = discover_sidecar_frames(args.lowres_depth_root, video_id, "lowres_depth")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    depth_dir = args.output_dir / "depth"
    confidence_dir = args.output_dir / "confidence"
    shuffled_dir = args.output_dir / "confidence-shuffled"
    for directory in (depth_dir, confidence_dir, shuffled_dir):
        directory.mkdir(parents=True, exist_ok=True)

    selected_records: list[dict] = []
    confidence_arrays: list[np.ndarray] = []
    with tarfile.open(args.archive, "r") as archive:
        frames = discover_frames(archive, video_id)
        by_timestamp = {frame.timestamp: frame for frame in frames}
        missing = [timestamp for timestamp in selected_timestamps if timestamp not in by_timestamp]
        if missing:
            raise ValueError(f"selected timestamps are missing from CA-1M archive: {missing}")

        for selected_index, timestamp in enumerate(selected_timestamps):
            frame = by_timestamp[timestamp]
            depth = decode_depth(read_member(archive, frame.members["wide/depth"])).astype("<f4")
            intrinsics = parse_intrinsics(read_member(archive, frame.members["wide/depth/k"]))
            pose = parse_pose(read_member(archive, frame.members["gt/rt"]))
            timestamp_seconds = int(timestamp) / 1_000_000_000.0
            confidence_match = nearest_sidecar_frame(confidence_frames, timestamp_seconds, SIDE_CAR_MAX_DELTA_SECONDS)
            witness_match = nearest_sidecar_frame(witness_frames, timestamp_seconds, SIDE_CAR_MAX_DELTA_SECONDS)
            if confidence_match is None or witness_match is None:
                raise ValueError(f"selected U3 frame {timestamp} has no sidecar match within 20 ms")
            confidence_frame, confidence_delta = confidence_match
            witness_frame, witness_delta = witness_match
            from PIL import Image
            raw_confidence = np.asarray(Image.open(confidence_frame.path))
            raw_witness = np.asarray(Image.open(witness_frame.path))
            ca1m_depth_mm = np.rint(depth.astype(np.float64) * MM_TO_M).astype(np.int64)
            orientation = infer_orientation_transform(raw_witness, ca1m_depth_mm)
            oriented_confidence = apply_discrete_transform(raw_confidence, orientation.transform)
            if oriented_confidence.shape != depth.shape:
                raise ValueError(
                    f"oriented confidence {oriented_confidence.shape} differs from CA-1M depth {depth.shape}"
                )
            raw_values = np.unique(oriented_confidence)
            if not set(int(value) for value in raw_values).issubset({0, 1, 2}):
                raise ValueError(f"ARKitScenes confidence contains unexpected levels {raw_values.tolist()}")
            mapped_confidence = np.take(
                np.asarray([0, 128, 255], dtype=np.uint8), oriented_confidence.astype(np.int64)
            )
            confidence_arrays.append(mapped_confidence)

            depth_path = depth_dir / f"{selected_index:02d}.f32"
            confidence_path = confidence_dir / f"{selected_index:02d}.u8"
            depth.tofile(depth_path)
            mapped_confidence.tofile(confidence_path)
            quaternion = matrix_to_quaternion_wxyz(pose[:3, :3])
            selected_records.append({
                "frameId": selected_index + 1,
                "timestampNanoseconds": int(timestamp),
                "width": int(depth.shape[1]),
                "height": int(depth.shape[0]),
                "intrinsics": [float(value) for value in intrinsics],
                "poseQuaternionWxyz": quaternion,
                "poseTranslationMetres": [float(value) for value in pose[:3, 3]],
                "depthPath": str(depth_path.relative_to(args.output_dir)),
                "confidencePath": str(confidence_path.relative_to(args.output_dir)),
                "confidenceJoinDeltaMilliseconds": float(confidence_delta * 1000.0),
                "orientationWitnessJoinDeltaMilliseconds": float(witness_delta * 1000.0),
                "sidecarOrientationTransform": orientation.transform,
                "orientationWitnessMedianAbsErrorMillimetres": float(orientation.median_abs_error_mm),
                "depth": depth,
                "pose": pose,
            })

        shuffled_arrays = shuffled_confidence(confidence_arrays, int(study["methods"][-1]["seed"]))
        for selected_index, shuffled in enumerate(shuffled_arrays):
            shuffled_path = shuffled_dir / f"{selected_index:02d}.u8"
            shuffled.tofile(shuffled_path)
            selected_records[selected_index]["shuffledConfidencePath"] = str(
                shuffled_path.relative_to(args.output_dir)
            )

        volume_spec = study["volume"]
        bounds = dense_bounds(
            selected_records,
            pixel_stride=int(volume_spec["boundsPixelStride"]),
            lower_quantile=float(volume_spec["boundsLowerQuantile"]),
            upper_quantile=float(volume_spec["boundsUpperQuantile"]),
            padding=float(volume_spec["paddingMetres"]),
            minimum_voxel=float(volume_spec["minimumVoxelSizeMetres"]),
            maximum_axis_voxels=int(volume_spec["maximumAxisVoxels"]),
        )

        reference_spec = study["referenceSampling"]
        reference_points, reference_candidates = build_reference(
            archive,
            frames,
            scene=scene,
            pixel_stride=int(reference_spec["sourcePixelStride"]),
            maximum_points=int(reference_spec["maximumReferencePoints"]),
        )

    reference_path = args.output_dir / "reference-faro.ply"
    write_binary_ply(reference_path, reference_points)

    manifest_frames = []
    for record in selected_records:
        manifest_frames.append({key: value for key, value in record.items() if key not in {"depth", "pose"}})
    uncertainty = study["frozenUncertaintyModel"]
    manifest = {
        "schemaVersion": 1,
        "study": study["id"],
        "scene": scene,
        "videoId": video_id,
        "cameraConvention": "+X right, +Y down, +Z forward",
        "poseConvention": "camera-to-world in FARO laser-scanner coordinates",
        "volume": bounds,
        "uncertainty": {
            "minimumSigmaMetres": uncertainty["minimumSigmaMetres"],
            "maximumSigmaMetres": uncertainty["maximumSigmaMetres"],
            "depthNoiseFloorMetres": uncertainty["depthNoiseFloorMetres"],
            "depthNoiseQuadraticMetresPerMetreSquared": uncertainty["depthNoiseQuadraticMetresPerMetreSquared"],
            "sensorConfidencePenalty": uncertainty["sensorConfidencePenalty"],
            "poseTranslationFloorMetres": uncertainty["poseTranslationFloorMetres"],
            "poseTranslationScaleMetres": uncertainty["poseTranslationScaleMetres"],
            "referenceSigmaMetres": uncertainty["referenceSigmaMetres"],
            "minimumPrecisionWeight": uncertainty["minimumPrecisionWeight"],
            "maximumPrecisionWeight": uncertainty["maximumPrecisionWeight"],
        },
        "frames": manifest_frames,
        "reference": {
            "path": str(reference_path.relative_to(args.output_dir)),
            "candidatePointsAfterFixedStride": reference_candidates,
            "retainedPoints": len(reference_points),
            "pixelStride": reference_spec["sourcePixelStride"],
            "selection": reference_spec["downsampling"],
        },
    }
    manifest_path = args.output_dir / "scene-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    ledger = {
        "ok": True,
        "stage": "U3-ca1m-scene-preparation",
        "scene": scene,
        "archive": str(args.archive),
        "archiveSha256": sha256_file(args.archive),
        "studySha256": sha256_file(args.study),
        "modelSha256": sha256_file(args.model),
        "preflightSha256": sha256_file(args.preflight),
        "poseGateSha256": sha256_file(args.pose_gate),
        "sceneManifest": str(manifest_path),
        "sceneManifestSha256": sha256_file(manifest_path),
        "reference": str(reference_path),
        "referenceSha256": sha256_file(reference_path),
        "selectedTimestampsNanoseconds": [int(value) for value in selected_timestamps],
        "volume": bounds,
        "referenceCandidatePoints": reference_candidates,
        "referenceRetainedPoints": len(reference_points),
    }
    ledger_path = args.output_dir / "prepare-ledger.json"
    ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n")
    print(json.dumps(ledger, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
