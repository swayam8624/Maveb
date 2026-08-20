#!/usr/bin/env python3
"""Prepare frozen U6b Gaussian visibility assets and held-out FARO targets without rendering."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import tarfile

import numpy as np
from PIL import Image

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
    nearest_sidecar_frame,
)
from prepare_u3_ca1m_scene import sha256_file, shuffled_confidence
from prepare_u5a_gaussian_depth import (
    camera_to_world_points,
    covariance_batch,
    target_indices,
    world_to_camera_payload,
    write_gaussian_ply,
)
from prepare_u6a_opacity_visibility import (
    assert_only_opacity_changed,
    opacity_logit,
    opacity_probability,
    parse_ascii_gaussian_ply,
    write_opacity_variant,
)


STUDY_ID = "metric-uncertainty-u6b-opacity-visibility-confirmatory-v1"
PROTOCOL_SHA256 = "0c58590d7c71c24797d583bd2681c1fc8994028d9b188b1fbe5fb5a4c4e1b3e3"
ACQUISITION_SHA256 = "b0ce48a6c3cbf0ab8a037b5df7db80753aac0063ffba733d63ac5bf0b76ee5a9"
PREFLIGHT_SHA256 = "64fe0e95b0b2667b0141c6f3ec435116b725724e9b68b1be21cf05b225a39190"
MODEL_SHA256 = "744cdfce9763f5d2ecd9c9a4e53385f66d8bba7cbc047e11729189053a85e17a"
EXPECTED_VIDEOS = ["42898811", "45261121", "47895341", "47332915", "47331971"]
EXPECTED_SCENES = [f"ca1m-{video}" for video in EXPECTED_VIDEOS]
METHODS = (
    "depth-only-fixed-opacity",
    "calibrated-relative-precision-opacity",
    "shuffled-relative-precision-opacity",
)
SOURCE_COUNT = 8
TARGET_COUNT = 8
PIXEL_STRIDE = 4
MIN_DEPTH_METRES = 0.05
MAX_DEPTH_METRES = 20.0
MAX_SIDECAR_DELTA_SECONDS = 0.020


def validate_protocol(path: Path) -> dict:
    if sha256_file(path) != PROTOCOL_SHA256:
        raise ValueError("U6b protocol SHA mismatch")
    payload = json.loads(path.read_text())
    if payload.get("id") != STUDY_ID or not payload.get("frozen"):
        raise ValueError("U6b protocol identity/frozen flag mismatch")
    if payload.get("status") != "preregistered-before-confirmatory-asset-acquisition":
        raise ValueError("U6b protocol status mismatch")
    videos = [str(item["videoId"]) for item in payload["confirmatorySplit"]["videos"]]
    if videos != EXPECTED_VIDEOS:
        raise ValueError(f"U6b protocol video order mismatch: {videos}")
    if payload["frozenPredictiveModel"]["sha256"] != MODEL_SHA256:
        raise ValueError("U6b predictive model SHA mismatch")
    if int(payload["sourceFrameSelection"]["viewCount"]) != SOURCE_COUNT:
        raise ValueError("U6b source view count changed")
    if int(payload["sourceGaussianSampling"]["pixelStride"]) != PIXEL_STRIDE:
        raise ValueError("U6b source Gaussian stride changed")
    if int(payload["targetViewSelection"]["count"]) != TARGET_COUNT:
        raise ValueError("U6b target view count changed")
    method_ids = tuple(item["id"] for item in payload["methods"])
    if method_ids != METHODS:
        raise ValueError(f"U6b method order changed: {method_ids}")
    return payload


def validate_acquisition(path: Path) -> dict:
    if sha256_file(path) != ACQUISITION_SHA256:
        raise ValueError("U6b acquisition ledger SHA mismatch")
    payload = json.loads(path.read_text())
    if payload.get("study") != STUDY_ID or payload.get("status") != "acquired-after-frozen-clean-plan":
        raise ValueError("U6b acquisition ledger does not authorize preparation")
    videos = [str(item["videoId"]) for item in payload.get("entries", [])]
    if videos != EXPECTED_VIDEOS:
        raise ValueError(f"U6b acquisition video order mismatch: {videos}")
    for item in payload["entries"]:
        archive = Path(item["ca1mArchive"])
        if not archive.is_file() or sha256_file(archive) != item["ca1mArchiveSha256"]:
            raise ValueError(f"U6b CA-1M archive hash mismatch for {item['videoId']}")
        confidence_zip = Path(item["confidenceZip"])
        lowres_zip = Path(item["lowresDepthZip"])
        if not confidence_zip.is_file() or sha256_file(confidence_zip) != item["confidenceZipSha256"]:
            raise ValueError(f"U6b confidence ZIP hash mismatch for {item['videoId']}")
        if not lowres_zip.is_file() or sha256_file(lowres_zip) != item["lowresDepthZipSha256"]:
            raise ValueError(f"U6b lowres-depth ZIP hash mismatch for {item['videoId']}")
    return payload


def validate_preflight(path: Path) -> dict:
    if sha256_file(path) != PREFLIGHT_SHA256:
        raise ValueError("U6b input preflight SHA mismatch")
    payload = json.loads(path.read_text())
    if payload.get("study") != STUDY_ID or payload.get("status") != "passed":
        raise ValueError("U6b input preflight did not pass")
    if payload.get("acquisitionLedgerSha256") != ACQUISITION_SHA256:
        raise ValueError("U6b input preflight acquisition SHA mismatch")
    if payload.get("protocolSha256") != PROTOCOL_SHA256:
        raise ValueError("U6b input preflight protocol SHA mismatch")
    if not payload.get("noRepresentationOutcomeProduced"):
        raise ValueError("U6b input preflight claim boundary changed")
    videos = [str(scene["videoId"]) for scene in payload.get("scenes", [])]
    if videos != EXPECTED_VIDEOS:
        raise ValueError(f"U6b preflight video order mismatch: {videos}")
    if not all(scene.get("scenePassed") for scene in payload["scenes"]):
        raise ValueError("U6b preflight contains a failed scene")
    return payload


def source_records(preflight_scene: dict) -> list[dict]:
    records = preflight_scene["primaryEightViewSelection"]
    if len(records) != SOURCE_COUNT:
        raise ValueError(f"U6b {preflight_scene['videoId']} does not have eight preflight sources")
    indices = [int(item["sourceIndex"]) for item in records]
    if indices != list(range(SOURCE_COUNT)):
        raise ValueError(f"U6b source order changed for {preflight_scene['videoId']}")
    timestamps = [str(item["timestampNanoseconds"]) for item in records]
    if len(set(timestamps)) != SOURCE_COUNT:
        raise ValueError(f"U6b source timestamps are not unique for {preflight_scene['videoId']}")
    for item in records:
        if not item.get("sidecarMatched") or not item.get("orientationAccepted"):
            raise ValueError(f"U6b preflight source is not authorized for {preflight_scene['videoId']}")
        if not item.get("confidenceLevelsAndShapeValid"):
            raise ValueError(f"U6b preflight confidence shape/levels failed for {preflight_scene['videoId']}")
    return records


def confidence_histogram(values: np.ndarray) -> dict[str, int]:
    counts = Counter(int(value) for value in np.asarray(values, dtype=np.uint8).reshape(-1).tolist())
    return {str(key): int(counts.get(key, 0)) for key in (0, 128, 255)}


def map_confidence(raw: np.ndarray) -> np.ndarray:
    if raw.ndim == 3 and raw.shape[-1] == 1:
        raw = raw[..., 0]
    if raw.ndim != 2:
        raise ValueError(f"U6b confidence image is not single-channel: {raw.shape}")
    unique = {int(value) for value in np.unique(raw)}
    if not unique.issubset({0, 1, 2}):
        raise ValueError(f"U6b confidence contains unexpected raw levels: {sorted(unique)}")
    return np.take(np.asarray([0, 128, 255], dtype=np.uint8), raw.astype(np.int64))


def write_target_manifest(
    *,
    archive_path: Path,
    video_id: str,
    scene: str,
    source_timestamps: set[str],
    target_root: Path,
    selection_rule: str,
) -> tuple[Path, list[int]]:
    target_root.mkdir(parents=True, exist_ok=True)
    targets: list[dict] = []
    with tarfile.open(archive_path, "r") as archive:
        complete = discover_frames(archive, video_id)
        eligible = [frame for frame in complete if frame.timestamp not in source_timestamps]
        indices = target_indices(len(eligible), TARGET_COUNT)
        selected = [eligible[index] for index in indices]
        if len({frame.timestamp for frame in selected}) != TARGET_COUNT:
            raise ValueError(f"U6b target selection is not unique for {scene}")
        for index, frame in enumerate(selected):
            faro_depth = decode_depth(read_member(archive, frame.members["gt/depth"])).astype("<f4")
            intrinsics = parse_intrinsics(read_member(archive, frame.members["gt/depth/k"]))
            pose = parse_pose(read_member(archive, frame.members["gt/rt"]))
            depth_path = target_root / f"{index:02d}-faro.f32"
            faro_depth.tofile(depth_path)
            world_to_camera, camera_position = world_to_camera_payload(pose)
            targets.append(
                {
                    "targetIndex": index,
                    "eligibleIndex": indices[index],
                    "timestampNanoseconds": int(frame.timestamp),
                    "width": int(faro_depth.shape[1]),
                    "height": int(faro_depth.shape[0]),
                    "intrinsics": [float(value) for value in intrinsics],
                    "cameraWorldPosition": camera_position,
                    "worldToCameraRowMajor": world_to_camera,
                    "faroDepthPath": str(depth_path.resolve()),
                    "faroDepthSha256": sha256_file(depth_path),
                }
            )
    payload = {
        "schemaVersion": 1,
        "study": STUDY_ID,
        "scene": scene,
        "videoId": video_id,
        "sourceTimestampsNanoseconds": sorted(int(value) for value in source_timestamps),
        "eligibleCompleteFrameCountAfterSourceExclusion": len(eligible),
        "selectionRule": selection_rule,
        "targets": targets,
    }
    manifest = target_root.parent / "targets.json"
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return manifest, [target["timestampNanoseconds"] for target in targets]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--acquisition-ledger", type=Path, required=True)
    parser.add_argument("--input-preflight", type=Path, required=True)
    parser.add_argument("--arkit-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    protocol = validate_protocol(args.protocol)
    acquisition = validate_acquisition(args.acquisition_ledger)
    preflight = validate_preflight(args.input_preflight)

    final_path = args.output_root / "preparation.json"
    if final_path.exists():
        raise ValueError("U6b preparation.json already exists; preparation will not be overwritten")
    if (args.output_root / "result.json").exists():
        raise ValueError("U6b result already exists")
    if args.output_root.exists() and list(args.output_root.glob("scenes/*/renders/*")):
        raise ValueError("U6b render outcomes already exist")
    if args.output_root.exists() and list(args.output_root.glob("scenes/*/*/gaussians.ply")):
        raise ValueError("U6b Gaussian assets already exist before preparation")
    args.output_root.mkdir(parents=True, exist_ok=True)

    acquisition_by_video = {str(item["videoId"]): item for item in acquisition["entries"]}
    preflight_by_video = {str(item["videoId"]): item for item in preflight["scenes"]}
    model = protocol["frozenPredictiveModel"]
    floor = float(model["a"])
    quadratic = float(model["b"])
    k = float(model["k"])
    base_opacity = float(protocol["methods"][0]["opacity"])
    base_opacity_logit = math.log(base_opacity / (1.0 - base_opacity))
    pixel_sigma = PIXEL_STRIDE / math.sqrt(12.0)
    scene_records: list[dict] = []

    for video_id, scene in zip(EXPECTED_VIDEOS, EXPECTED_SCENES, strict=True):
        acquired = acquisition_by_video[video_id]
        preflight_scene = preflight_by_video[video_id]
        sources = source_records(preflight_scene)
        archive_path = Path(acquired["ca1mArchive"])
        scene_root = args.output_root / "scenes" / scene
        scene_root.mkdir(parents=True, exist_ok=True)

        confidence_frames = discover_sidecar_frames(
            args.arkit_root / "raw" / "Validation" / video_id / "confidence",
            video_id,
            "confidence",
        )
        full_confidence_arrays: list[np.ndarray] = []
        source_payloads: list[dict] = []

        with tarfile.open(archive_path, "r") as archive:
            complete = discover_frames(archive, video_id)
            by_timestamp = {frame.timestamp: frame for frame in complete}
            for source in sources:
                timestamp = str(source["timestampNanoseconds"])
                frame = by_timestamp.get(timestamp)
                if frame is None:
                    raise ValueError(f"U6b frozen source {video_id}/{timestamp} is missing from CA-1M")
                depth = decode_depth(read_member(archive, frame.members["wide/depth"])).astype("<f4")
                intrinsics = parse_intrinsics(read_member(archive, frame.members["wide/depth/k"]))
                pose = parse_pose(read_member(archive, frame.members["gt/rt"]))
                match = nearest_sidecar_frame(
                    confidence_frames,
                    int(timestamp) / 1_000_000_000.0,
                    MAX_SIDECAR_DELTA_SECONDS,
                )
                if match is None:
                    raise ValueError(f"U6b frozen source {video_id}/{timestamp} lost confidence sidecar match")
                confidence_frame, confidence_delta = match
                raw_confidence = np.asarray(Image.open(confidence_frame.path))
                oriented = apply_discrete_transform(raw_confidence, source["bestOrientation"]["transform"])
                mapped = map_confidence(oriented)
                if mapped.shape != depth.shape or list(mapped.shape) != list(source["orientedConfidenceShape"]):
                    raise ValueError(f"U6b oriented confidence shape changed for {video_id}/{timestamp}")
                actual_delta_ms = float(confidence_delta * 1000.0)
                if abs(actual_delta_ms - float(source["confidenceJoinDeltaMilliseconds"])) > 1.0e-6:
                    raise ValueError(f"U6b confidence join delta changed for {video_id}/{timestamp}")
                full_confidence_arrays.append(mapped)
                source_payloads.append(
                    {
                        "sourceIndex": int(source["sourceIndex"]),
                        "timestampNanoseconds": int(timestamp),
                        "depth": depth,
                        "intrinsics": intrinsics,
                        "pose": pose,
                        "confidence": mapped,
                        "orientationTransform": source["bestOrientation"]["transform"],
                        "confidenceJoinDeltaMilliseconds": actual_delta_ms,
                    }
                )

        shuffled_full = shuffled_confidence(full_confidence_arrays, 42)
        full_intact_stream = np.concatenate([array.reshape(-1) for array in full_confidence_arrays])
        full_shuffled_stream = np.concatenate([array.reshape(-1) for array in shuffled_full])
        full_intact_histogram = confidence_histogram(full_intact_stream)
        full_shuffled_histogram = confidence_histogram(full_shuffled_stream)
        if full_intact_histogram != full_shuffled_histogram:
            raise ValueError(f"U6b full confidence distribution changed under shuffle for {scene}")

        positions_chunks: list[np.ndarray] = []
        log_scale_chunks: list[np.ndarray] = []
        quaternion_chunks: list[np.ndarray] = []
        intact_chunks: list[np.ndarray] = []
        shuffled_chunks: list[np.ndarray] = []
        source_records_out: list[dict] = []

        for payload, shuffled_image in zip(source_payloads, shuffled_full, strict=True):
            depth = payload["depth"]
            height, width = depth.shape
            ys, xs = np.meshgrid(
                np.arange(0, height, PIXEL_STRIDE, dtype=np.int64),
                np.arange(0, width, PIXEL_STRIDE, dtype=np.int64),
                indexing="ij",
            )
            sampled_depth = depth[ys, xs].astype(np.float64)
            valid = (
                np.isfinite(sampled_depth)
                & (sampled_depth >= MIN_DEPTH_METRES)
                & (sampled_depth <= MAX_DEPTH_METRES)
            )
            if not np.any(valid):
                raise ValueError(f"U6b source produced no valid Gaussian samples: {video_id}/{payload['timestampNanoseconds']}")
            z = sampled_depth[valid]
            x = xs[valid].astype(np.float64)
            y = ys[valid].astype(np.float64)
            positions = camera_to_world_points(z, x, y, payload["intrinsics"], payload["pose"])
            sigma0 = floor + quadratic * z * z
            log_scales, quaternions = covariance_batch(
                x,
                y,
                z,
                payload["intrinsics"],
                payload["pose"],
                sigma0,
                pixel_sigma,
            )
            intact = payload["confidence"][ys, xs][valid].astype(np.uint8, copy=True)
            shuffled = shuffled_image[ys, xs][valid].astype(np.uint8, copy=True)
            positions_chunks.append(positions)
            log_scale_chunks.append(log_scales)
            quaternion_chunks.append(quaternions)
            intact_chunks.append(intact)
            shuffled_chunks.append(shuffled)
            source_records_out.append(
                {
                    "sourceIndex": payload["sourceIndex"],
                    "timestampNanoseconds": payload["timestampNanoseconds"],
                    "orientationTransform": payload["orientationTransform"],
                    "confidenceJoinDeltaMilliseconds": payload["confidenceJoinDeltaMilliseconds"],
                    "sampledPrimitiveCount": int(z.size),
                    "intactPrimitiveConfidenceHistogram": confidence_histogram(intact),
                    "shuffledPrimitiveConfidenceHistogram": confidence_histogram(shuffled),
                }
            )

        positions = np.concatenate(positions_chunks, axis=0)
        log_scales = np.concatenate(log_scale_chunks, axis=0)
        quaternions = np.concatenate(quaternion_chunks, axis=0)
        intact_stream = np.concatenate(intact_chunks)
        shuffled_stream = np.concatenate(shuffled_chunks)
        primitive_count = int(positions.shape[0])
        if not (
            log_scales.shape == positions.shape
            and quaternions.shape == (primitive_count, 4)
            and intact_stream.shape == (primitive_count,)
            and shuffled_stream.shape == (primitive_count,)
        ):
            raise ValueError(f"U6b primitive/confidence alignment failed for {scene}")

        baseline_path = scene_root / METHODS[0] / "gaussians.ply"
        write_gaussian_ply(
            baseline_path,
            positions,
            log_scales,
            quaternions,
            base_opacity_logit,
        )
        header, rows, _ = parse_ascii_gaussian_ply(baseline_path)
        if len(rows) != primitive_count:
            raise ValueError(f"U6b baseline PLY row count mismatch for {scene}")

        candidate_prob = opacity_probability(intact_stream, base_opacity=base_opacity, k=k)
        shuffled_prob = opacity_probability(shuffled_stream, base_opacity=base_opacity, k=k)
        candidate_path = scene_root / METHODS[1] / "gaussians.ply"
        shuffled_path = scene_root / METHODS[2] / "gaussians.ply"
        write_opacity_variant(candidate_path, header, rows, opacity_logit(candidate_prob))
        write_opacity_variant(shuffled_path, header, rows, opacity_logit(shuffled_prob))
        assert_only_opacity_changed(baseline_path, candidate_path)
        assert_only_opacity_changed(baseline_path, shuffled_path)

        method_records = {
            METHODS[0]: {
                "gaussianPath": str(baseline_path.resolve()),
                "gaussianSha256": sha256_file(baseline_path),
                "primitiveCount": primitive_count,
                "opacityProbabilityMin": base_opacity,
                "opacityProbabilityMedian": base_opacity,
                "opacityProbabilityMax": base_opacity,
                "geometryCovarianceRole": "frozen-depth-only-covariance",
            },
            METHODS[1]: {
                "gaussianPath": str(candidate_path.resolve()),
                "gaussianSha256": sha256_file(candidate_path),
                "primitiveCount": primitive_count,
                "fullConfidenceHistogram": full_intact_histogram,
                "primitiveConfidenceHistogram": confidence_histogram(intact_stream),
                "opacityProbabilityMin": float(np.min(candidate_prob)),
                "opacityProbabilityMedian": float(np.median(candidate_prob)),
                "opacityProbabilityMax": float(np.max(candidate_prob)),
                "onlyOpacityChangedFromBaseline": True,
            },
            METHODS[2]: {
                "gaussianPath": str(shuffled_path.resolve()),
                "gaussianSha256": sha256_file(shuffled_path),
                "primitiveCount": primitive_count,
                "fullConfidenceHistogram": full_shuffled_histogram,
                "primitiveConfidenceHistogram": confidence_histogram(shuffled_stream),
                "opacityProbabilityMin": float(np.min(shuffled_prob)),
                "opacityProbabilityMedian": float(np.median(shuffled_prob)),
                "opacityProbabilityMax": float(np.max(shuffled_prob)),
                "onlyOpacityChangedFromBaseline": True,
                "shuffleSeed": 42,
                "shuffleScope": "full oriented eight-view confidence stream before depth-valid Gaussian sampling",
            },
        }

        target_manifest, target_timestamps = write_target_manifest(
            archive_path=archive_path,
            video_id=video_id,
            scene=scene,
            source_timestamps={str(item["timestampNanoseconds"]) for item in sources},
            target_root=scene_root / "targets",
            selection_rule=protocol["targetViewSelection"]["indexRule"],
        )
        scene_records.append(
            {
                "scene": scene,
                "videoId": video_id,
                "visitId": str(preflight_scene["visitId"]),
                "sourceCount": SOURCE_COUNT,
                "sourceRecords": source_records_out,
                "primitiveCount": primitive_count,
                "fullConfidenceHistogramPreservedByShuffle": full_intact_histogram == full_shuffled_histogram,
                "methods": method_records,
                "targetManifestPath": str(target_manifest.resolve()),
                "targetManifestSha256": sha256_file(target_manifest),
                "targetTimestampsNanoseconds": target_timestamps,
                "noRenderedDepthProduced": True,
                "noU6bMetricsProduced": True,
            }
        )
        print(
            json.dumps(
                {
                    "u6bPreparation": {
                        "scene": scene,
                        "primitives": primitive_count,
                        "targets": target_timestamps,
                        "fullConfidenceHistogram": full_intact_histogram,
                        "candidatePrimitiveHistogram": method_records[METHODS[1]]["primitiveConfidenceHistogram"],
                        "shuffledPrimitiveHistogram": method_records[METHODS[2]]["primitiveConfidenceHistogram"],
                    }
                },
                sort_keys=True,
            ),
            flush=True,
        )

    payload = {
        "schemaVersion": 1,
        "study": STUDY_ID,
        "stage": "U6b-confirmatory-preparation",
        "status": "prepared-no-u6b-render-or-metric-outcomes",
        "protocolSha256": sha256_file(args.protocol),
        "acquisitionLedgerSha256": sha256_file(args.acquisition_ledger),
        "inputPreflightSha256": sha256_file(args.input_preflight),
        "methods": list(METHODS),
        "pixelStride": PIXEL_STRIDE,
        "sourceDepthRangeMetres": [MIN_DEPTH_METRES, MAX_DEPTH_METRES],
        "baseOpacity": base_opacity,
        "sensorConfidencePenalty": k,
        "shuffleScope": "full oriented eight-view confidence stream before depth-valid Gaussian sampling",
        "scenes": scene_records,
        "noRenderedDepthProduced": True,
        "noU6bMetricsProduced": True,
    }
    final_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
