#!/usr/bin/env python3
"""Run the frozen U3b CA-1M pose-convention preflight on confirmatory scenes.

This wrapper deliberately reuses the geometric measurements implemented by
`ca1m_u3_pose_preflight.py` while applying only the U3b preregistered pass rule.
It does not use ARKit confidence, ARKit-vs-FARO residuals, mesh outputs, or
geometry metrics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ca1m_u3_pose_preflight import inspect_archive

EXPECTED_STUDY = "metric-uncertainty-u3b-relative-confidence-transfer-v1"
EXPECTED_SPLIT_SHA = "f7269b595bafe5e50d975b3026a958b1a4b0ef2bcc695f4494d161f8aa285e56"
EXPECTED_PROTOCOL_SHA = "f42fb12bb855e660c3cf4d77e5dd4200b73136baa73981434b54c98b43e63a6d"
EXPECTED_ACQUISITION_LEDGER_SHA = "3675d61e89599a36641e8d4ddb0dd28ce9722030af3b4672b70c401973695f73"
EXPECTED_VIDEOS = ["48458481", "48018737", "45261587", "42897538", "48018375"]


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
    inverse = float(validation["inverseMedianOfPairMedianErrorsMetres"])
    return pair_count > 0 and wins > pair_count / 2 and direct < inverse


def load_acquisition_ledger(path: Path) -> dict:
    if sha256_file(path) != EXPECTED_ACQUISITION_LEDGER_SHA:
        raise ValueError("U3b acquisition ledger SHA does not match the frozen acquired artifact")
    payload = json.loads(path.read_text())
    if payload.get("study") != EXPECTED_STUDY:
        raise ValueError("acquisition ledger study id mismatch")
    if payload.get("status") != "acquired-after-clean-preregistered-plan":
        raise ValueError("acquisition ledger does not authorize confirmatory pose preflight")
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acquisition-ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--primary-views", type=int, default=8)
    parser.add_argument("--validation-pairs", type=int, default=16)
    parser.add_argument("--pixel-stride", type=int, default=16)
    args = parser.parse_args()

    if args.primary_views != 8:
        raise ValueError("U3b protocol freezes primary view count at 8")
    if args.validation_pairs != 16:
        raise ValueError("U3b pose preflight freezes 16 requested adjacent-frame validation pairs")
    if args.pixel_stride != 16:
        raise ValueError("U3b pose preflight freezes pixel stride at 16")

    ledger_path = args.acquisition_ledger.resolve()
    ledger = load_acquisition_ledger(ledger_path)
    scenes = []

    for entry in ledger["entries"]:
        video = str(entry["videoId"])
        archive = Path(entry["ca1mArchive"]).resolve()
        scene = inspect_archive(
            archive,
            video,
            primary_views=args.primary_views,
            validation_pairs=args.validation_pairs,
            pixel_stride=args.pixel_stride,
        )
        validation = scene["poseConventionValidation"]
        legacy_pass = bool(validation.pop("passed"))
        frozen_pass = frozen_pose_rule(validation)
        validation["legacyImplementationPassed"] = legacy_pass
        validation["frozenU3bRulePassed"] = frozen_pass
        scenes.append(scene)

    passed = all(scene["poseConventionValidation"]["frozenU3bRulePassed"] for scene in scenes)
    payload = {
        "schemaVersion": 1,
        "study": EXPECTED_STUDY,
        "stage": "U3b-ca1m-pose-preflight",
        "status": "passed" if passed else "failed",
        "acquisitionLedgerSha256": sha256_file(ledger_path),
        "splitSha256": EXPECTED_SPLIT_SHA,
        "protocolSha256": EXPECTED_PROTOCOL_SHA,
        "poseInterpretation": "gt/RT is camera-to-world in FARO laser-scanner coordinates",
        "cameraConvention": "+X right, +Y down, +Z forward",
        "frozenPassRule": (
            "released interpretation must have lower scene median cross-projection depth disagreement "
            "and win a majority of comparable adjacent-frame pairs in every confirmatory scene"
        ),
        "legacyThresholdExcluded": (
            "The historical U3 implementation-only minimum comparable-pair threshold is not part of "
            "the frozen U3b protocol and is recorded only as a legacy diagnostic."
        ),
        "frameSelectionFormula": "nearest index to i*(N-1)/(K-1), ties to lower index",
        "primaryViewCount": args.primary_views,
        "validationPairCountRequested": args.validation_pairs,
        "pixelStride": args.pixel_stride,
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
