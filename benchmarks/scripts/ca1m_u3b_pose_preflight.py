#!/usr/bin/env python3
"""Finalize the frozen U3b CA-1M pose-convention preflight.

The FARO cross-projection measurements are consumed from the immutable
pose-support diagnostic. This script does not select new validation pairs or
rerun reconstruction. It applies the original U3b rule where the inverse pose
has support and the separately frozen zero-inverse-support clarification where
that control is undefined.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import tarfile

from ca1m_u3_pose_preflight import (
    decode_depth,
    discover_frames,
    parse_intrinsics,
    parse_pose,
    quantile_indices,
    read_member,
)

EXPECTED_STUDY = "metric-uncertainty-u3b-relative-confidence-transfer-v1"
EXPECTED_SPLIT_SHA = "f7269b595bafe5e50d975b3026a958b1a4b0ef2bcc695f4494d161f8aa285e56"
EXPECTED_PROTOCOL_SHA = "f42fb12bb855e660c3cf4d77e5dd4200b73136baa73981434b54c98b43e63a6d"
EXPECTED_ACQUISITION_LEDGER_SHA = "3675d61e89599a36641e8d4ddb0dd28ce9722030af3b4672b70c401973695f73"
EXPECTED_DIAGNOSTIC_SHA = "61d16eaecde6e6ab40cf51c87a81c8a75127923b4c3ec2dade3a18ec7fcadec7"
EXPECTED_CLARIFICATION_SHA = "5f01d7061db61e0fd365226c46619dc833d87c956d61de89e5a9e1b3429a49b4"
EXPECTED_VIDEOS = ["48458481", "48018737", "45261587", "42897538", "48018375"]
PRIMARY_VIEWS = 8
VALIDATION_PAIRS = 16
PIXEL_STRIDE = 16


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def frozen_pose_rule(validation: dict) -> bool:
    pair_count = int(validation["pairCount"])
    wins = int(validation["cameraToWorldBetterPairCount"])
    direct = float(validation["cameraToWorldMedianOfPairMedianErrorsMetres"])
    inverse = validation.get("inverseMedianOfPairMedianErrorsMetres")
    direct_supported = int(validation.get("cameraToWorldSupportedPairCount", pair_count))
    inverse_supported = int(validation.get("inverseSupportedPairCount", pair_count))
    requested = int(validation.get("requestedPairCount", VALIDATION_PAIRS))

    if inverse_supported == 0:
        return direct_supported == requested and requested == VALIDATION_PAIRS
    if inverse is None:
        return False
    return pair_count > 0 and wins > pair_count / 2 and direct < float(inverse)


def load_acquisition_ledger(path: Path) -> dict:
    if sha256_file(path) != EXPECTED_ACQUISITION_LEDGER_SHA:
        raise ValueError("U3b acquisition ledger SHA mismatch")
    payload = json.loads(path.read_text())
    if payload.get("study") != EXPECTED_STUDY:
        raise ValueError("acquisition ledger study id mismatch")
    if payload.get("status") != "acquired-after-clean-preregistered-plan":
        raise ValueError("acquisition ledger does not authorize pose preflight")
    if payload.get("splitSha256") != EXPECTED_SPLIT_SHA:
        raise ValueError("acquisition ledger split SHA mismatch")
    if payload.get("protocolSha256") != EXPECTED_PROTOCOL_SHA:
        raise ValueError("acquisition ledger protocol SHA mismatch")
    entries = payload.get("entries", [])
    videos = [str(entry["videoId"]) for entry in entries]
    if videos != EXPECTED_VIDEOS:
        raise ValueError(f"acquisition ledger video order mismatch: {videos}")
    for entry in entries:
        archive = Path(entry["ca1mArchive"])
        if not archive.is_file():
            raise FileNotFoundError(archive)
        if sha256_file(archive) != entry["ca1mArchiveSha256"]:
            raise ValueError(f"CA-1M archive hash mismatch for {entry['videoId']}")
    return payload


def load_diagnostic(path: Path) -> dict:
    if sha256_file(path) != EXPECTED_DIAGNOSTIC_SHA:
        raise ValueError("U3b pose-support diagnostic SHA mismatch")
    payload = json.loads(path.read_text())
    if payload.get("study") != EXPECTED_STUDY:
        raise ValueError("pose-support diagnostic study id mismatch")
    if payload.get("status") != "diagnostic-only-no-gate-change":
        raise ValueError("pose-support diagnostic status mismatch")
    if payload.get("acquisitionLedgerSha256") != EXPECTED_ACQUISITION_LEDGER_SHA:
        raise ValueError("pose-support diagnostic acquisition SHA mismatch")
    if payload.get("validationPairCountRequested") != VALIDATION_PAIRS:
        raise ValueError("pose-support diagnostic pair count mismatch")
    if payload.get("pixelStride") != PIXEL_STRIDE:
        raise ValueError("pose-support diagnostic stride mismatch")
    videos = [str(scene["videoId"]) for scene in payload.get("scenes", [])]
    if videos != EXPECTED_VIDEOS:
        raise ValueError(f"pose-support diagnostic video order mismatch: {videos}")
    return payload


def validate_clarification(path: Path) -> dict:
    if sha256_file(path) != EXPECTED_CLARIFICATION_SHA:
        raise ValueError("U3b pose clarification SHA mismatch")
    payload = json.loads(path.read_text())
    if payload.get("id") != "metric-uncertainty-u3b-pose-clarification-v1":
        raise ValueError("pose clarification id mismatch")
    if payload.get("status") != "frozen-pre-reconstruction-clarification":
        raise ValueError("pose clarification status mismatch")
    if payload.get("diagnosticSha256") != EXPECTED_DIAGNOSTIC_SHA:
        raise ValueError("pose clarification diagnostic SHA mismatch")
    return payload


def selected_primary_frames(archive_path: Path, video_id: str) -> tuple[int, list[dict]]:
    with tarfile.open(archive_path, "r") as archive:
        frames = discover_frames(archive, video_id)
        indices = quantile_indices(len(frames), PRIMARY_VIEWS)
        records = []
        for original_index in indices:
            frame = frames[original_index]
            pose = parse_pose(read_member(archive, frame.members["gt/rt"]))
            arkit_depth = decode_depth(read_member(archive, frame.members["wide/depth"]))
            faro_depth = decode_depth(read_member(archive, frame.members["gt/depth"]))
            arkit_k = parse_intrinsics(read_member(archive, frame.members["wide/depth/k"]))
            faro_k = parse_intrinsics(read_member(archive, frame.members["gt/depth/k"]))
            records.append(
                {
                    "originalCompleteFrameIndex": original_index,
                    "timestampNanoseconds": int(frame.timestamp),
                    "arkitDepthShape": list(arkit_depth.shape),
                    "faroDepthShape": list(faro_depth.shape),
                    "arkitDepthIntrinsics": list(arkit_k),
                    "faroDepthIntrinsics": list(faro_k),
                    "cameraToWorldTranslationMetres": [float(value) for value in pose[:3, 3]],
                }
            )
    return len(frames), records


def validation_from_diagnostic(scene: dict) -> dict:
    direct_medians = [
        float(pair["cameraToWorld"]["medianAbsDepthErrorMetres"])
        for pair in scene["pairs"]
        if pair["cameraToWorld"]["medianAbsDepthErrorMetres"] is not None
    ]
    inverse_medians = [
        float(pair["inverseInterpretation"]["medianAbsDepthErrorMetres"])
        for pair in scene["pairs"]
        if pair["inverseInterpretation"]["medianAbsDepthErrorMetres"] is not None
    ]
    if not direct_medians:
        raise ValueError(f"camera-to-world has no FARO support for {scene['videoId']}")

    validation = {
        "requestedPairCount": int(scene["requestedPairCount"]),
        "pairCount": int(scene["mutuallyComparablePairCount"]),
        "cameraToWorldSupportedPairCount": int(scene["cameraToWorldSupportedPairCount"]),
        "inverseSupportedPairCount": int(scene["inverseSupportedPairCount"]),
        "cameraToWorldBetterPairCount": int(scene["cameraToWorldWinsAmongComparable"]),
        "cameraToWorldMedianOfPairMedianErrorsMetres": float(statistics.median(direct_medians)),
        "inverseMedianOfPairMedianErrorsMetres": (
            float(statistics.median(inverse_medians)) if inverse_medians else None
        ),
        "pairs": scene["pairs"],
    }
    validation["clarificationApplied"] = len(inverse_medians) == 0
    validation["decisionMode"] = (
        "zero-inverse-support-clarification"
        if validation["clarificationApplied"]
        else "original-frozen-rule"
    )
    validation["frozenU3bRulePassed"] = frozen_pose_rule(validation)
    return validation


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acquisition-ledger", type=Path, required=True)
    parser.add_argument("--diagnostic", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--clarification",
        type=Path,
        default=repo_root / "benchmarks/experiments/metric-uncertainty-u3b-pose-clarification-v1.json",
    )
    args = parser.parse_args()

    ledger_path = args.acquisition_ledger.resolve()
    diagnostic_path = args.diagnostic.resolve()
    clarification_path = args.clarification.resolve()
    ledger = load_acquisition_ledger(ledger_path)
    diagnostic = load_diagnostic(diagnostic_path)
    validate_clarification(clarification_path)

    diagnostic_by_video = {str(scene["videoId"]): scene for scene in diagnostic["scenes"]}
    scenes = []
    for entry in ledger["entries"]:
        video = str(entry["videoId"])
        complete_frames, selected = selected_primary_frames(Path(entry["ca1mArchive"]).resolve(), video)
        validation = validation_from_diagnostic(diagnostic_by_video[video])
        scenes.append(
            {
                "videoId": video,
                "archive": entry["ca1mArchive"],
                "completeFrames": complete_frames,
                "primaryEightViewSelection": selected,
                "poseConventionValidation": validation,
            }
        )

    passed = all(scene["poseConventionValidation"]["frozenU3bRulePassed"] for scene in scenes)
    payload = {
        "schemaVersion": 2,
        "study": EXPECTED_STUDY,
        "stage": "U3b-ca1m-pose-preflight",
        "status": "passed" if passed else "failed",
        "acquisitionLedgerSha256": sha256_file(ledger_path),
        "poseSupportDiagnosticSha256": sha256_file(diagnostic_path),
        "poseClarificationSha256": sha256_file(clarification_path),
        "splitSha256": EXPECTED_SPLIT_SHA,
        "protocolSha256": EXPECTED_PROTOCOL_SHA,
        "poseInterpretation": "gt/RT is camera-to-world in FARO laser-scanner coordinates",
        "cameraConvention": "+X right, +Y down, +Z forward",
        "frozenPassRule": (
            "original U3b majority+lower-median rule when inverse support exists; "
            "if inverse support is zero, pass only with camera-to-world support on all 16 frozen pairs"
        ),
        "clarificationTiming": "after pose-support diagnostic and before any U3b reconstruction outcome",
        "frameSelectionFormula": "nearest index to i*(N-1)/(K-1), ties to lower index",
        "primaryViewCount": PRIMARY_VIEWS,
        "validationPairCountRequested": VALIDATION_PAIRS,
        "pixelStride": PIXEL_STRIDE,
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
