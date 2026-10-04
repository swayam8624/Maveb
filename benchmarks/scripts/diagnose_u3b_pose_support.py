#!/usr/bin/env python3
"""Diagnose support for the frozen U3b pose preflight without changing its gate.

Uses the exact frozen 16 adjacent-frame pairs and pixel stride 16. This script
never reconstructs geometry and never changes the preregistered pass rule. It
only records whether each competing pose interpretation has valid FARO
cross-projection support on each already-selected pair.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tarfile

from ca1m_u3_pose_preflight import (
    cross_project,
    decode_depth,
    discover_frames,
    pair_indices,
    parse_intrinsics,
    parse_pose,
    read_member,
)

EXPECTED_ACQUISITION_LEDGER_SHA = "3675d61e89599a36641e8d4ddb0dd28ce9722030af3b4672b70c401973695f73"
EXPECTED_VIDEOS = ["48458481", "48018737", "45261587", "42897538", "48018375"]
VALIDATION_PAIRS = 16
PIXEL_STRIDE = 16


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def inspect_support(path: Path, video_id: str) -> dict:
    direct_medians: list[float] = []
    inverse_medians: list[float] = []
    reports: list[dict] = []

    with tarfile.open(path, "r") as archive:
        frames = discover_frames(archive, video_id)
        selected_pair_indices = pair_indices(len(frames), VALIDATION_PAIRS)

        for source_index in selected_pair_indices:
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
                pixel_stride=PIXEL_STRIDE,
            )
            inverse = cross_project(
                source_depth,
                source_k,
                source_pose,
                target_depth,
                target_k,
                target_pose,
                camera_to_world=False,
                pixel_stride=PIXEL_STRIDE,
            )

            if direct[1] is not None:
                direct_medians.append(float(direct[1]))
            if inverse[1] is not None:
                inverse_medians.append(float(inverse[1]))

            reports.append(
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
        r for r in reports
        if r["cameraToWorld"]["medianAbsDepthErrorMetres"] is not None
        and r["inverseInterpretation"]["medianAbsDepthErrorMetres"] is not None
    ]
    direct_wins = sum(
        r["cameraToWorld"]["medianAbsDepthErrorMetres"]
        < r["inverseInterpretation"]["medianAbsDepthErrorMetres"]
        for r in comparable
    )

    return {
        "videoId": video_id,
        "completeFrames": len(frames),
        "requestedPairCount": VALIDATION_PAIRS,
        "pixelStride": PIXEL_STRIDE,
        "cameraToWorldSupportedPairCount": len(direct_medians),
        "inverseSupportedPairCount": len(inverse_medians),
        "mutuallyComparablePairCount": len(comparable),
        "cameraToWorldWinsAmongComparable": direct_wins,
        "pairs": reports,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acquisition-ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    ledger_path = args.acquisition_ledger.resolve()
    if sha256_file(ledger_path) != EXPECTED_ACQUISITION_LEDGER_SHA:
        raise ValueError("acquisition ledger SHA mismatch")
    ledger = json.loads(ledger_path.read_text())
    videos = [str(e["videoId"]) for e in ledger["entries"]]
    if videos != EXPECTED_VIDEOS:
        raise ValueError(f"unexpected confirmatory video order: {videos}")

    scenes = []
    for entry in ledger["entries"]:
        archive = Path(entry["ca1mArchive"]).resolve()
        if sha256_file(archive) != entry["ca1mArchiveSha256"]:
            raise ValueError(f"archive hash mismatch for {entry['videoId']}")
        scene = inspect_support(archive, str(entry["videoId"]))
        scenes.append(scene)
        print(
            json.dumps(
                {
                    "videoId": scene["videoId"],
                    "directSupported": scene["cameraToWorldSupportedPairCount"],
                    "inverseSupported": scene["inverseSupportedPairCount"],
                    "comparable": scene["mutuallyComparablePairCount"],
                    "directWins": scene["cameraToWorldWinsAmongComparable"],
                },
                sort_keys=True,
            )
        )

    payload = {
        "schemaVersion": 1,
        "study": "metric-uncertainty-u3b-relative-confidence-transfer-v1",
        "stage": "U3b-pose-support-diagnostic",
        "status": "diagnostic-only-no-gate-change",
        "acquisitionLedgerSha256": sha256_file(ledger_path),
        "validationPairCountRequested": VALIDATION_PAIRS,
        "pixelStride": PIXEL_STRIDE,
        "note": "No reconstruction metrics are produced and the frozen U3b pose pass rule is not modified by this diagnostic.",
        "scenes": scenes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(args.output.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
