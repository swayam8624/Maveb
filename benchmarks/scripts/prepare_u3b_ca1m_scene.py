#!/usr/bin/env python3
"""Prepare one frozen U3b confirmatory CA-1M scene without reconstructing geometry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tarfile

import numpy as np

from ca1m_u3_pose_preflight import decode_depth, discover_frames, parse_intrinsics, parse_pose, read_member
from ca1m_uncertainty_samples import (
    apply_discrete_transform,
    discover_sidecar_frames,
    infer_orientation_transform,
    nearest_sidecar_frame,
)
from prepare_u3_ca1m_scene import (
    MM_TO_M,
    SIDE_CAR_MAX_DELTA_SECONDS,
    build_reference,
    dense_bounds,
    matrix_to_quaternion_wxyz,
    sha256_file,
    shuffled_confidence,
    video_id_from_archive,
    write_binary_ply,
)


STUDY_ID = "metric-uncertainty-u3b-relative-confidence-transfer-v1"
ENGINE_STUDY_ID = "metric-uncertainty-u3-dense-tsdf-v1"
STUDY_SHA256 = "f42fb12bb855e660c3cf4d77e5dd4200b73136baa73981434b54c98b43e63a6d"
MODEL_SHA256 = "744cdfce9763f5d2ecd9c9a4e53385f66d8bba7cbc047e11729189053a85e17a"
POSE_SHA256 = "692479544ceff75e02fd3645138eab5a5e38d83e397ff3ec5de9ce1a3d468f6d"
EXPECTED_VIDEOS = ["48458481", "48018737", "45261587", "42897538", "48018375"]


def validate_study(path: Path) -> dict:
    if sha256_file(path) != STUDY_SHA256:
        raise ValueError("U3b study SHA differs from the preregistered protocol")
    payload = json.loads(path.read_text())
    if payload.get("id") != STUDY_ID or not payload.get("frozen"):
        raise ValueError("U3b study is not the frozen confirmatory protocol")
    videos = [str(item["videoId"]) for item in payload["confirmatorySplit"]["videos"]]
    if videos != EXPECTED_VIDEOS:
        raise ValueError(f"U3b confirmatory video order mismatch: {videos}")
    if payload["frozenPredictiveModel"]["sha256"] != MODEL_SHA256:
        raise ValueError("U3b protocol references a different predictive model")
    return payload


def validate_pose(path: Path, video_id: str) -> tuple[dict, list[str]]:
    if sha256_file(path) != POSE_SHA256:
        raise ValueError("U3b pose-preflight SHA differs from the frozen passed artifact")
    payload = json.loads(path.read_text())
    if payload.get("study") != STUDY_ID or payload.get("status") != "passed":
        raise ValueError("U3b pose preflight does not authorize preparation")
    scene = next((item for item in payload["scenes"] if str(item["videoId"]) == video_id), None)
    if scene is None or not scene["poseConventionValidation"].get("frozenU3bRulePassed"):
        raise ValueError(f"U3b pose rule did not pass for {video_id}")
    timestamps = [str(item["timestampNanoseconds"]) for item in scene["primaryEightViewSelection"]]
    if len(timestamps) != 8 or len(set(timestamps)) != 8:
        raise ValueError(f"U3b pose artifact does not contain eight unique primary views for {video_id}")
    return scene, timestamps


def relative_uncertainty(adapter: dict) -> dict:
    config = dict(adapter["relativeManifestUncertaintyConfig"])
    expected = adapter["equivalence"]["expectedWeights"]
    k = float(config["sensorConfidencePenalty"])
    actual = {
        "confidenceU8_0": 1.0 / (1.0 + k) ** 2,
        "confidenceU8_128": 1.0 / (1.0 + k * (1.0 - 128.0 / 255.0)) ** 2,
        "confidenceU8_255": 1.0,
    }
    for key, value in expected.items():
        if abs(float(value) - actual[key]) > 1.0e-15:
            raise ValueError(f"U3b engine adapter expected weight mismatch for {key}")
    attainable_minimum = actual["confidenceU8_0"]
    if float(config["minimumPrecisionWeight"]) >= attainable_minimum:
        raise ValueError("U3b implementation sentinel would alter the attainable relative weight range")
    if float(config["maximumPrecisionWeight"]) != 1.0:
        raise ValueError("U3b relative precision maximum must remain exactly one")
    if float(config["minimumSigmaMetres"]) > 1.0 or float(config["maximumSigmaMetres"]) < 1.0 + k:
        raise ValueError("U3b sigma clamp would alter the preregistered transfer")
    return config


def legacy_uncertainty(repo: Path) -> dict:
    path = repo / "benchmarks/experiments/metric-uncertainty-u3-dense-tsdf-v1.json"
    payload = json.loads(path.read_text())
    frozen = payload["frozenUncertaintyModel"]
    if frozen["sha256"] != MODEL_SHA256:
        raise ValueError("legacy U3-v1 uncertainty model SHA mismatch")
    return {
        "minimumSigmaMetres": float(frozen["minimumSigmaMetres"]),
        "maximumSigmaMetres": float(frozen["maximumSigmaMetres"]),
        "depthNoiseFloorMetres": float(frozen["depthNoiseFloorMetres"]),
        "depthNoiseQuadraticMetresPerMetreSquared": float(
            frozen["depthNoiseQuadraticMetresPerMetreSquared"]
        ),
        "sensorConfidencePenalty": float(frozen["sensorConfidencePenalty"]),
        "poseTranslationFloorMetres": float(frozen["poseTranslationFloorMetres"]),
        "poseTranslationScaleMetres": float(frozen["poseTranslationScaleMetres"]),
        "referenceSigmaMetres": float(frozen["referenceSigmaMetres"]),
        "minimumPrecisionWeight": float(frozen["minimumPrecisionWeight"]),
        "maximumPrecisionWeight": float(frozen["maximumPrecisionWeight"]),
    }


def engine_manifest(*, scene: str, video_id: str, frames: list[dict], bounds: dict,
                    uncertainty: dict, reference: dict, research_role: str,
                    adapter_sha: str) -> dict:
    return {
        "schemaVersion": 1,
        "study": ENGINE_STUDY_ID,
        "researchStudy": STUDY_ID,
        "researchMethodFamily": research_role,
        "u3bEngineAdapterSha256": adapter_sha,
        "u3bPosePreflightSha256": POSE_SHA256,
        "u3bProtocolSha256": STUDY_SHA256,
        "scene": scene,
        "videoId": video_id,
        "cameraConvention": "+X right, +Y down, +Z forward",
        "poseConvention": "camera-to-world in FARO laser-scanner coordinates",
        "volume": bounds,
        "uncertainty": uncertainty,
        "frames": frames,
        "reference": reference,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--confidence-root", type=Path, required=True)
    parser.add_argument("--lowres-depth-root", type=Path, required=True)
    parser.add_argument("--pose-preflight", type=Path, required=True)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[2]
    video_id = video_id_from_archive(args.archive)
    scene = f"ca1m-{video_id}"
    if video_id not in EXPECTED_VIDEOS:
        raise ValueError(f"{video_id} is not in the frozen U3b confirmatory set")
    for path in (args.archive, args.pose_preflight, args.study, args.model, args.adapter):
        if not path.is_file():
            raise FileNotFoundError(path)
    if sha256_file(args.model) != MODEL_SHA256:
        raise ValueError("U3b requires the exact frozen U1b model")
    study = validate_study(args.study)
    _, selected_timestamps = validate_pose(args.pose_preflight, video_id)

    adapter = json.loads(args.adapter.read_text())
    if adapter.get("study") != STUDY_ID or adapter.get("status") != "frozen-before-any-u3b-reconstruction-outcome":
        raise ValueError("U3b engine adapter is not the frozen pre-outcome adapter")
    if adapter.get("parentProtocolSha256") != STUDY_SHA256 or adapter.get("posePreflightSha256") != POSE_SHA256:
        raise ValueError("U3b engine adapter no longer matches protocol/pose inputs")
    adapter_sha = sha256_file(args.adapter)
    relative_config = relative_uncertainty(adapter)
    legacy_config = legacy_uncertainty(repo)

    if (args.output_dir / "primary").exists():
        raise ValueError("U3b preparation is locked after a primary reconstruction directory exists")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    depth_dir = args.output_dir / "depth"
    confidence_dir = args.output_dir / "confidence"
    shuffled_dir = args.output_dir / "confidence-shuffled"
    for directory in (depth_dir, confidence_dir, shuffled_dir):
        directory.mkdir(parents=True, exist_ok=True)

    confidence_frames = discover_sidecar_frames(args.confidence_root, video_id, "confidence")
    witness_frames = discover_sidecar_frames(args.lowres_depth_root, video_id, "lowres_depth")
    selected_records: list[dict] = []
    confidence_arrays: list[np.ndarray] = []

    with tarfile.open(args.archive, "r") as archive:
        frames = discover_frames(archive, video_id)
        by_timestamp = {frame.timestamp: frame for frame in frames}
        missing = [timestamp for timestamp in selected_timestamps if timestamp not in by_timestamp]
        if missing:
            raise ValueError(f"frozen U3b primary timestamps are missing from archive: {missing}")

        for selected_index, timestamp in enumerate(selected_timestamps):
            frame = by_timestamp[timestamp]
            depth = decode_depth(read_member(archive, frame.members["wide/depth"])).astype("<f4")
            intrinsics = parse_intrinsics(read_member(archive, frame.members["wide/depth/k"]))
            pose = parse_pose(read_member(archive, frame.members["gt/rt"]))
            timestamp_seconds = int(timestamp) / 1_000_000_000.0
            confidence_match = nearest_sidecar_frame(
                confidence_frames, timestamp_seconds, SIDE_CAR_MAX_DELTA_SECONDS
            )
            witness_match = nearest_sidecar_frame(
                witness_frames, timestamp_seconds, SIDE_CAR_MAX_DELTA_SECONDS
            )
            if confidence_match is None or witness_match is None:
                raise ValueError(f"frozen U3b frame {timestamp} has no sidecar match within 20 ms")
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
            selected_records.append(
                {
                    "frameId": selected_index + 1,
                    "timestampNanoseconds": int(timestamp),
                    "width": int(depth.shape[1]),
                    "height": int(depth.shape[0]),
                    "intrinsics": [float(value) for value in intrinsics],
                    "poseQuaternionWxyz": matrix_to_quaternion_wxyz(pose[:3, :3]),
                    "poseTranslationMetres": [float(value) for value in pose[:3, 3]],
                    "depthPath": str(depth_path.relative_to(args.output_dir)),
                    "confidencePath": str(confidence_path.relative_to(args.output_dir)),
                    "confidenceJoinDeltaMilliseconds": float(confidence_delta * 1000.0),
                    "orientationWitnessJoinDeltaMilliseconds": float(witness_delta * 1000.0),
                    "sidecarOrientationTransform": orientation.transform,
                    "orientationWitnessMedianAbsErrorMillimetres": float(
                        orientation.median_abs_error_mm
                    ),
                    "depth": depth,
                    "pose": pose,
                }
            )

        shuffled_arrays = shuffled_confidence(confidence_arrays, 42)
        for selected_index, shuffled in enumerate(shuffled_arrays):
            shuffled_path = shuffled_dir / f"{selected_index:02d}.u8"
            shuffled.tofile(shuffled_path)
            selected_records[selected_index]["shuffledConfidencePath"] = str(
                shuffled_path.relative_to(args.output_dir)
            )

        volume_spec = study["volumeAndReference"]
        bounds = dense_bounds(
            selected_records,
            pixel_stride=int(volume_spec["boundsPixelStride"]),
            lower_quantile=float(volume_spec["boundsLowerQuantile"]),
            upper_quantile=float(volume_spec["boundsUpperQuantile"]),
            padding=float(volume_spec["paddingMetres"]),
            minimum_voxel=float(volume_spec["minimumVoxelSizeMetres"]),
            maximum_axis_voxels=int(volume_spec["maximumAxisVoxels"]),
        )
        if abs(float(bounds["maximumWeight"]) - float(volume_spec["maximumAccumulatedWeight"])) > 1e-12:
            raise ValueError("prepared dense TSDF maximum weight differs from U3b protocol")

        reference_points, reference_candidates = build_reference(
            archive,
            frames,
            scene=scene,
            pixel_stride=int(volume_spec["referenceSourcePixelStride"]),
            maximum_points=int(volume_spec["maximumReferencePoints"]),
        )

    reference_path = args.output_dir / "reference-faro.ply"
    write_binary_ply(reference_path, reference_points)
    manifest_frames = [
        {key: value for key, value in record.items() if key not in {"depth", "pose"}}
        for record in selected_records
    ]
    reference_meta = {
        "path": str(reference_path.relative_to(args.output_dir)),
        "candidatePointsAfterFixedStride": reference_candidates,
        "retainedPoints": len(reference_points),
        "pixelStride": int(study["volumeAndReference"]["referenceSourcePixelStride"]),
        "selection": study["volumeAndReference"]["referenceDownsampling"],
    }

    legacy_manifest = engine_manifest(
        scene=scene,
        video_id=video_id,
        frames=manifest_frames,
        bounds=bounds,
        uncertainty=legacy_config,
        reference=reference_meta,
        research_role="legacy-u3v1-absolute-inverse-variance",
        adapter_sha=adapter_sha,
    )
    relative_manifest = engine_manifest(
        scene=scene,
        video_id=video_id,
        frames=manifest_frames,
        bounds=bounds,
        uncertainty=relative_config,
        reference=reference_meta,
        research_role="relative-confidence-precision",
        adapter_sha=adapter_sha,
    )
    legacy_manifest_path = args.output_dir / "scene-manifest-legacy.json"
    relative_manifest_path = args.output_dir / "scene-manifest-relative.json"
    legacy_manifest_path.write_text(json.dumps(legacy_manifest, indent=2, sort_keys=True) + "\n")
    relative_manifest_path.write_text(json.dumps(relative_manifest, indent=2, sort_keys=True) + "\n")

    ledger = {
        "ok": True,
        "stage": "U3b-ca1m-scene-preparation",
        "scene": scene,
        "videoId": video_id,
        "archive": str(args.archive),
        "archiveSha256": sha256_file(args.archive),
        "studySha256": sha256_file(args.study),
        "modelSha256": sha256_file(args.model),
        "posePreflightSha256": sha256_file(args.pose_preflight),
        "engineAdapterSha256": adapter_sha,
        "legacyManifest": str(legacy_manifest_path),
        "legacyManifestSha256": sha256_file(legacy_manifest_path),
        "relativeManifest": str(relative_manifest_path),
        "relativeManifestSha256": sha256_file(relative_manifest_path),
        "reference": str(reference_path),
        "referenceSha256": sha256_file(reference_path),
        "referenceCandidatePointsAfterFixedStride": reference_candidates,
        "referenceRetainedPoints": len(reference_points),
        "selectedTimestampsNanoseconds": [int(value) for value in selected_timestamps],
        "volume": bounds,
        "orientationTransforms": [record["sidecarOrientationTransform"] for record in manifest_frames],
        "maximumConfidenceJoinDeltaMilliseconds": max(
            float(record["confidenceJoinDeltaMilliseconds"]) for record in manifest_frames
        ),
        "maximumOrientationWitnessJoinDeltaMilliseconds": max(
            float(record["orientationWitnessJoinDeltaMilliseconds"]) for record in manifest_frames
        ),
        "noReconstructionOutcomesProduced": True,
    }
    print(json.dumps(ledger, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
