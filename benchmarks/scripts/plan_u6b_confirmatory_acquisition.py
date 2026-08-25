#!/usr/bin/env python3
"""Plan U6b confirmatory acquisition without downloading or modifying dataset assets."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


STUDY_ID = "metric-uncertainty-u6b-opacity-visibility-confirmatory-v1"
EXPECTED_SPLIT_SHA256 = "d22366afd77d3407e53d5152d313522d559ee57e9ec995d96102c299dc55f5ff"
EXPECTED_METADATA_SHA256 = "bc855db7fa6666dcab7997434949fd8d89027d3b9c3fdbda8a30896e80d0742b"
EXPECTED_ARKIT_METADATA_BLOB_SHA = "2b347453aff47f4bb1dc79c71a8ed9e25e2bb5f3"
EXPECTED_CA1M_VAL_BLOB_SHA = "5b155412995a07a1413f1539b0f0eda95d20959c"
EXPECTED_VIDEOS = [
    ("42898811", "434650"),
    ("45261121", "466628"),
    ("47895341", "472297"),
    ("47332915", "469249"),
    ("47331971", "470821"),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_metadata_evidence(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError("U6b public metadata evidence is missing")
    if sha256_file(path) != EXPECTED_METADATA_SHA256:
        raise ValueError("U6b public metadata evidence SHA differs")
    payload = json.loads(path.read_text())
    if (
        payload.get("study") != STUDY_ID
        or payload.get("status") != "frozen-before-confirmatory-asset-acquisition"
        or payload.get("assetAcquisitionPerformed") is not False
    ):
        raise ValueError("U6b public metadata evidence boundary differs")
    selected = [
        (str(item["videoId"]), str(item["visitId"]), str(item["fold"]))
        for item in payload.get("selectedValidationRows", [])
    ]
    expected = [(video, visit, "Validation") for video, visit in EXPECTED_VIDEOS]
    if selected != expected:
        raise ValueError("U6b public metadata selected rows differ")
    sources = payload.get("publicSources", {})
    arkit = sources.get("arkitScenesRawSplit", {})
    ca1m = sources.get("ca1mValidationList", {})
    if arkit.get("gitBlobSha") != EXPECTED_ARKIT_METADATA_BLOB_SHA:
        raise ValueError("U6b ARKitScenes metadata blob SHA differs")
    if ca1m.get("gitBlobSha") != EXPECTED_CA1M_VAL_BLOB_SHA:
        raise ValueError("U6b CA-1M validation metadata blob SHA differs")
    binding = payload.get("selectionBinding", {})
    if binding.get("splitSha256") != EXPECTED_SPLIT_SHA256:
        raise ValueError("U6b public metadata does not bind the frozen split")
    return payload


def validate_frozen_inputs(
    split_path: Path, protocol_path: Path, metadata_path: Path
) -> tuple[dict, dict, dict]:
    if not split_path.is_file() or not protocol_path.is_file():
        raise FileNotFoundError("U6b frozen split/protocol is missing")
    if sha256_file(split_path) != EXPECTED_SPLIT_SHA256:
        raise ValueError("U6b split SHA differs from the frozen selection")
    split = json.loads(split_path.read_text())
    protocol = json.loads(protocol_path.read_text())
    metadata = validate_metadata_evidence(metadata_path)
    if split.get("study") != STUDY_ID:
        raise ValueError("U6b split study id differs")
    if split.get("selectionStatus") != "frozen-before-confirmatory-asset-acquisition":
        raise ValueError("U6b split is not frozen before acquisition")
    split_pairs = [
        (str(item["videoId"]), str(item["visitId"]))
        for item in split.get("confirmatoryVideos", [])
    ]
    if split_pairs != EXPECTED_VIDEOS:
        raise ValueError("U6b split membership/order differs")
    if len({visit for _, visit in split_pairs}) != 5:
        raise ValueError("U6b visits are not distinct")
    if (
        protocol.get("id") != STUDY_ID
        or protocol.get("status") != "preregistered-before-confirmatory-asset-acquisition"
        or protocol.get("frozen") is not True
    ):
        raise ValueError("U6b protocol is not frozen before acquisition")
    confirmatory = protocol.get("confirmatorySplit", {})
    if confirmatory.get("sha256") != EXPECTED_SPLIT_SHA256:
        raise ValueError("U6b protocol does not bind the frozen split SHA")
    protocol_pairs = [
        (str(item["videoId"]), str(item["visitId"]))
        for item in confirmatory.get("videos", [])
    ]
    if protocol_pairs != EXPECTED_VIDEOS:
        raise ValueError("U6b protocol scene membership/order differs")
    return split, protocol, metadata


def file_birth_time(path: Path) -> str | None:
    if not path.exists():
        return None
    value = getattr(path.stat(), "st_birthtime", None)
    if value is None:
        return None
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def asset_state(ca1m_root: Path, arkit_root: Path, video: str, visit: str) -> dict:
    ca1m_archive = ca1m_root / f"ca1m-val-{video}.tar"
    ca1m_partial = ca1m_archive.with_suffix(ca1m_archive.suffix + ".part")
    raw_root = arkit_root / "raw" / "Validation" / video
    confidence = raw_root / "confidence"
    lowres_depth = raw_root / "lowres_depth"
    confidence_zip = raw_root / "confidence.zip"
    lowres_zip = raw_root / "lowres_depth.zip"
    confidence_files = sorted(confidence.glob("*.png")) if confidence.is_dir() else []
    lowres_files = sorted(lowres_depth.glob("*.png")) if lowres_depth.is_dir() else []
    preexisting = bool(
        ca1m_archive.exists()
        or ca1m_partial.exists()
        or confidence_files
        or lowres_files
        or confidence_zip.exists()
        or lowres_zip.exists()
    )
    return {
        "videoId": video,
        "visitId": visit,
        "preexisting": preexisting,
        "ca1mArchive": str(ca1m_archive.resolve()),
        "ca1mArchivePresent": ca1m_archive.is_file(),
        "ca1mArchiveSha256": sha256_file(ca1m_archive) if ca1m_archive.is_file() else None,
        "ca1mArchiveBirthTimeUtc": file_birth_time(ca1m_archive),
        "ca1mPartialPresent": ca1m_partial.exists(),
        "confidenceDirectory": str(confidence.resolve()),
        "confidencePngCount": len(confidence_files),
        "confidenceZipPresent": confidence_zip.is_file(),
        "lowresDepthDirectory": str(lowres_depth.resolve()),
        "lowresDepthPngCount": len(lowres_files),
        "lowresDepthZipPresent": lowres_zip.is_file(),
    }


def build_plan(
    *,
    split_path: Path,
    protocol_path: Path,
    metadata_path: Path,
    ca1m_root: Path,
    arkit_root: Path,
) -> dict:
    split, _, metadata = validate_frozen_inputs(split_path, protocol_path, metadata_path)
    entries = [
        asset_state(ca1m_root, arkit_root, str(item["videoId"]), str(item["visitId"]))
        for item in split["confirmatoryVideos"]
    ]
    contaminated = [entry["videoId"] for entry in entries if entry["preexisting"]]
    clean = not contaminated
    return {
        "schemaVersion": 2,
        "study": STUDY_ID,
        "stage": "U6b-confirmatory-acquisition-plan",
        "createdAtUtc": utc_now(),
        "status": "clean-before-u6b-acquisition" if clean else "blocked-preexisting-u6b-assets",
        "canExecuteAcquisition": clean,
        "networkAccessPerformed": False,
        "datasetMutationPerformed": False,
        "splitSha256": sha256_file(split_path),
        "protocolSha256": sha256_file(protocol_path),
        "publicMetadataEvidenceSha256": sha256_file(metadata_path),
        "arkitRawSplitGitBlobSha": metadata["publicSources"]["arkitScenesRawSplit"]["gitBlobSha"],
        "ca1mValidationListGitBlobSha": metadata["publicSources"]["ca1mValidationList"]["gitBlobSha"],
        "localArkitMetadataCsvRequired": False,
        "ca1mRoot": str(ca1m_root.resolve()),
        "arkitRoot": str(arkit_root.resolve()),
        "preexistingVideoIds": contaminated,
        "entries": entries,
        "failurePolicy": (
            "Any preexisting selected U6b asset blocks confirmatory acquisition. "
            "Do not replace a room or delete evidence to manufacture a clean boundary."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--metadata-evidence", type=Path, required=True)
    parser.add_argument("--ca1m-root", type=Path, required=True)
    parser.add_argument("--arkit-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("U6b acquisition plan already exists; will not overwrite")
    plan = build_plan(
        split_path=args.split,
        protocol_path=args.protocol,
        metadata_path=args.metadata_evidence,
        ca1m_root=args.ca1m_root,
        arkit_root=args.arkit_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    print(json.dumps(plan, sort_keys=True))
    return 0 if plan["canExecuteAcquisition"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
