#!/usr/bin/env python3
"""Run frozen U6b pose and sidecar-orientation preflights before preparation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import tarfile

import numpy as np
from PIL import Image

from ca1m_u3_pose_preflight import (
    cross_project,
    decode_depth,
    discover_frames,
    pair_indices,
    parse_intrinsics,
    parse_pose,
    quantile_indices,
    read_member,
)
from ca1m_uncertainty_samples import (
    apply_discrete_transform,
    discover_sidecar_frames,
    nearest_sidecar_frame,
)

STUDY_ID = "metric-uncertainty-u6b-opacity-visibility-confirmatory-v1"
EXPECTED_ACQUISITION_SHA = "b0ce48a6c3cbf0ab8a037b5df7db80753aac0063ffba733d63ac5bf0b76ee5a9"
EXPECTED_SPLIT_SHA = "d22366afd77d3407e53d5152d313522d559ee57e9ec995d96102c299dc55f5ff"
EXPECTED_PROTOCOL_SHA = "0c58590d7c71c24797d583bd2681c1fc8994028d9b188b1fbe5fb5a4c4e1b3e3"
EXPECTED_VIDEOS = ["42898811", "45261121", "47895341", "47332915", "47331971"]
PRIMARY_VIEWS = 8
VALIDATION_PAIRS = 16
POSE_PIXEL_STRIDE = 16
SIDECAR_MAX_DELTA_SECONDS = 0.020
MINIMUM_ORIENTATION_PIXELS = 256
ORIENTATION_ABSOLUTE_ACCEPT_MM = 25.0
ORIENTATION_RELATIVE_ACCEPT_RATIO = 0.75
TRANSFORMS = (
    "identity",
    "rot90-cw",
    "rot180",
    "rot90-ccw",
    "flip-lr",
    "flip-ud",
    "transpose",
    "transverse",
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def inherited_pose_rule(validation: dict) -> bool:
    comparable = int(validation["mutuallyComparablePairCount"])
    wins = int(validation["cameraToWorldWinsAmongComparable"])
    direct_supported = int(validation["cameraToWorldSupportedPairCount"])
    inverse_supported = int(validation["inverseSupportedPairCount"])
    direct_median = validation["cameraToWorldMedianOfSupportedPairMediansMetres"]
    inverse_median = validation["inverseMedianOfSupportedPairMediansMetres"]
    if inverse_supported == 0:
        return direct_supported == VALIDATION_PAIRS
    if comparable <= 0 or direct_median is None or inverse_median is None:
        return False
    return wins > comparable / 2 and float(direct_median) < float(inverse_median)


def orientation_scores(raw_witness: np.ndarray, ca1m_depth_mm: np.ndarray) -> list[dict]:
    scores: list[dict] = []
    for transform in TRANSFORMS:
        transformed = apply_discrete_transform(raw_witness, transform)
        if transformed.shape != ca1m_depth_mm.shape:
            continue
        valid = (transformed > 0) & (ca1m_depth_mm > 0)
        count = int(np.count_nonzero(valid))
        if count < MINIMUM_ORIENTATION_PIXELS:
            continue
        errors = np.abs(
            transformed[valid].astype(np.float64)
            - ca1m_depth_mm[valid].astype(np.float64)
        )
        scores.append(
            {
                "transform": transform,
                "medianAbsErrorMillimetres": float(np.median(errors)),
                "p90AbsErrorMillimetres": float(np.percentile(errors, 90.0)),
                "validPixels": count,
            }
        )
    scores.sort(
        key=lambda x: (
            x["medianAbsErrorMillimetres"],
            x["p90AbsErrorMillimetres"],
            -x["validPixels"],
            x["transform"],
        )
    )
    return scores


def orientation_accepted(scores: list[dict]) -> bool:
    if not scores:
        return False
    best = float(scores[0]["medianAbsErrorMillimetres"])
    if best <= ORIENTATION_ABSOLUTE_ACCEPT_MM:
        return True
    if len(scores) < 2:
        return False
    second = float(scores[1]["medianAbsErrorMillimetres"])
    return best <= ORIENTATION_RELATIVE_ACCEPT_RATIO * second


def pose_validation(archive_path: Path, video_id: str) -> dict:
    direct_medians: list[float] = []
    inverse_medians: list[float] = []
    pairs: list[dict] = []
    with tarfile.open(archive_path, "r") as archive:
        frames = discover_frames(archive, video_id)
        for source_index in pair_indices(len(frames), VALIDATION_PAIRS):
            source = frames[source_index]
            target = frames[source_index + 1]
            source_depth = decode_depth(read_member(archive, source.members["gt/depth"]))
            target_depth = decode_depth(read_member(archive, target.members["gt/depth"]))
            source_k = parse_intrinsics(read_member(archive, source.members["gt/depth/k"]))
            target_k = parse_intrinsics(read_member(archive, target.members["gt/depth/k"]))
            source_pose = parse_pose(read_member(archive, source.members["gt/rt"]))
            target_pose = parse_pose(read_member(archive, target.members["gt/rt"]))
            direct = cross_project(
                source_depth,
                source_k,
                source_pose,
                target_depth,
                target_k,
                target_pose,
                camera_to_world=True,
                pixel_stride=POSE_PIXEL_STRIDE,
            )
            inverse = cross_project(
                source_depth,
                source_k,
                source_pose,
                target_depth,
                target_k,
                target_pose,
                camera_to_world=False,
                pixel_stride=POSE_PIXEL_STRIDE,
            )
            if direct[1] is not None:
                direct_medians.append(float(direct[1]))
            if inverse[1] is not None:
                inverse_medians.append(float(inverse[1]))
            pairs.append(
                {
                    "sourceTimestampNanoseconds": int(source.timestamp),
                    "targetTimestampNanoseconds": int(target.timestamp),
                    "cameraToWorld": {
                        "validCorrespondences": int(direct[0]),
                        "medianAbsDepthErrorMetres": direct[1],
                        "p90AbsDepthErrorMetres": direct[2],
                    },
                    "inverseInterpretation": {
                        "validCorrespondences": int(inverse[0]),
                        "medianAbsDepthErrorMetres": inverse[1],
                        "p90AbsDepthErrorMetres": inverse[2],
                    },
                }
            )
    comparable = [
        p
        for p in pairs
        if p["cameraToWorld"]["medianAbsDepthErrorMetres"] is not None
        and p["inverseInterpretation"]["medianAbsDepthErrorMetres"] is not None
    ]
    wins = sum(
        p["cameraToWorld"]["medianAbsDepthErrorMetres"]
        < p["inverseInterpretation"]["medianAbsDepthErrorMetres"]
        for p in comparable
    )
    result = {
        "requestedPairCount": VALIDATION_PAIRS,
        "pixelStride": POSE_PIXEL_STRIDE,
        "cameraToWorldSupportedPairCount": len(direct_medians),
        "inverseSupportedPairCount": len(inverse_medians),
        "mutuallyComparablePairCount": len(comparable),
        "cameraToWorldWinsAmongComparable": wins,
        "cameraToWorldMedianOfSupportedPairMediansMetres": (
            float(statistics.median(direct_medians)) if direct_medians else None
        ),
        "inverseMedianOfSupportedPairMediansMetres": (
            float(statistics.median(inverse_medians)) if inverse_medians else None
        ),
        "pairs": pairs,
    }
    result["decisionMode"] = (
        "inherited-u3b-zero-inverse-support-clarification"
        if len(inverse_medians) == 0
        else "inherited-u3b-original-majority-lower-median-rule"
    )
    result["passed"] = inherited_pose_rule(result)
    return result


def selected_source_frames(
    archive_path: Path,
    video_id: str,
    confidence_root: Path,
    lowres_root: Path,
) -> tuple[int, list[dict]]:
    confidence_frames = discover_sidecar_frames(confidence_root, video_id, "confidence")
    witness_frames = discover_sidecar_frames(lowres_root, video_id, "lowres_depth")
    records: list[dict] = []
    with tarfile.open(archive_path, "r") as archive:
        frames = discover_frames(archive, video_id)
        indices = quantile_indices(len(frames), PRIMARY_VIEWS)
        for source_index, frame_index in enumerate(indices):
            frame = frames[frame_index]
            depth = decode_depth(read_member(archive, frame.members["wide/depth"]))
            depth_mm = np.rint(depth * 1000.0).astype(np.int64)
            timestamp_seconds = int(frame.timestamp) / 1_000_000_000.0
            confidence_match = nearest_sidecar_frame(
                confidence_frames, timestamp_seconds, SIDECAR_MAX_DELTA_SECONDS
            )
            witness_match = nearest_sidecar_frame(
                witness_frames, timestamp_seconds, SIDECAR_MAX_DELTA_SECONDS
            )
            if confidence_match is None or witness_match is None:
                records.append(
                    {
                        "sourceIndex": source_index,
                        "originalCompleteFrameIndex": frame_index,
                        "timestampNanoseconds": int(frame.timestamp),
                        "sidecarMatched": False,
                        "orientationAccepted": False,
                    }
                )
                continue
            confidence_frame, confidence_delta = confidence_match
            witness_frame, witness_delta = witness_match
            raw_confidence = np.asarray(Image.open(confidence_frame.path))
            raw_witness = np.asarray(Image.open(witness_frame.path))
            scores = orientation_scores(raw_witness, depth_mm)
            accepted = orientation_accepted(scores)
            best = scores[0] if scores else None
            second = scores[1] if len(scores) > 1 else None
            confidence_levels_valid = False
            oriented_shape = None
            if best is not None:
                oriented = apply_discrete_transform(raw_confidence, best["transform"])
                oriented_shape = list(oriented.shape)
                values = set(int(v) for v in np.unique(oriented))
                confidence_levels_valid = values.issubset({0, 1, 2}) and oriented.shape == depth.shape
            records.append(
                {
                    "sourceIndex": source_index,
                    "originalCompleteFrameIndex": frame_index,
                    "timestampNanoseconds": int(frame.timestamp),
                    "sidecarMatched": True,
                    "confidenceJoinDeltaMilliseconds": float(confidence_delta * 1000.0),
                    "orientationWitnessJoinDeltaMilliseconds": float(witness_delta * 1000.0),
                    "bestOrientation": best,
                    "secondBestOrientation": second,
                    "orientationAccepted": accepted,
                    "confidenceLevelsAndShapeValid": confidence_levels_valid,
                    "orientedConfidenceShape": oriented_shape,
                    "ca1mDepthShape": list(depth.shape),
                }
            )
    return len(frames), records


def validate_ledger(path: Path) -> dict:
    if sha256_file(path) != EXPECTED_ACQUISITION_SHA:
        raise ValueError("U6b acquisition ledger SHA mismatch")
    payload = json.loads(path.read_text())
    if payload.get("study") != STUDY_ID or payload.get("status") != "acquired-after-frozen-clean-plan":
        raise ValueError("U6b acquisition ledger does not authorize preflight")
    if payload.get("splitSha256") != EXPECTED_SPLIT_SHA:
        raise ValueError("U6b acquisition split SHA mismatch")
    if payload.get("protocolSha256") != EXPECTED_PROTOCOL_SHA:
        raise ValueError("U6b acquisition protocol SHA mismatch")
    videos = [str(e["videoId"]) for e in payload.get("entries", [])]
    if videos != EXPECTED_VIDEOS:
        raise ValueError(f"U6b acquisition video order mismatch: {videos}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acquisition-ledger", type=Path, required=True)
    parser.add_argument("--arkit-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("U6b preflight output already exists; will not overwrite")
    ledger_path = args.acquisition_ledger.resolve()
    ledger = validate_ledger(ledger_path)
    scenes: list[dict] = []
    for entry in ledger["entries"]:
        video = str(entry["videoId"])
        archive = Path(entry["ca1mArchive"]).resolve()
        if not archive.is_file() or sha256_file(archive) != entry["ca1mArchiveSha256"]:
            raise ValueError(f"U6b archive integrity mismatch for {video}")
        confidence_root = args.arkit_root / "raw" / "Validation" / video / "confidence"
        lowres_root = args.arkit_root / "raw" / "Validation" / video / "lowres_depth"
        pose = pose_validation(archive, video)
        complete_frames, sources = selected_source_frames(
            archive, video, confidence_root, lowres_root
        )
        orientation_passed = all(
            s.get("sidecarMatched")
            and s.get("orientationAccepted")
            and s.get("confidenceLevelsAndShapeValid")
            for s in sources
        )
        scenes.append(
            {
                "videoId": video,
                "visitId": str(entry["visitId"]),
                "completeFrames": complete_frames,
                "poseConventionValidation": pose,
                "primaryEightViewSelection": sources,
                "orientationPreflightPassed": orientation_passed,
                "scenePassed": bool(pose["passed"] and orientation_passed),
            }
        )
    passed = all(scene["scenePassed"] for scene in scenes)
    payload = {
        "schemaVersion": 1,
        "study": STUDY_ID,
        "stage": "U6b-confirmatory-pose-and-orientation-preflight",
        "status": "passed" if passed else "failed",
        "acquisitionLedgerSha256": sha256_file(ledger_path),
        "splitSha256": EXPECTED_SPLIT_SHA,
        "protocolSha256": EXPECTED_PROTOCOL_SHA,
        "primaryViewCount": PRIMARY_VIEWS,
        "poseValidationPairCount": VALIDATION_PAIRS,
        "posePixelStride": POSE_PIXEL_STRIDE,
        "sidecarMaximumJoinDeltaMilliseconds": SIDECAR_MAX_DELTA_SECONDS * 1000.0,
        "orientationAcceptance": "best median <=25 mm OR best median <=75% of second-best median; >=256 valid witness pixels; no interpolation",
        "posePassRule": "inherit U3b majority+lower-median rule when inverse support exists; if inverse support is zero, camera-to-world must have support on all 16 frozen pairs",
        "noRepresentationOutcomeProduced": True,
        "scenes": scenes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(args.output)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
