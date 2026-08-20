#!/usr/bin/env python3
"""Plan U6b confirmatory acquisition without downloading or modifying dataset assets."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


STUDY_ID = "metric-uncertainty-u6b-opacity-visibility-confirmatory-v1"
EXPECTED_SPLIT_SHA256 = "d22366afd77d3407e53d5152d313522d559ee57e9ec995d96102c299dc55f5ff"
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


def load_raw_index(path: Path) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        required = {"video_id", "visit_id", "fold"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError("ARKitScenes raw split CSV lacks video_id/visit_id/fold")
        for row in reader:
            video = str(row["video_id"]).strip()
            if video:
                result[video] = (str(row["visit_id"]).strip(), str(row["fold"]).strip())
    return result


def validate_frozen_inputs(split_path: Path, protocol_path: Path) -> tuple[dict, dict]:
    if not split_path.is_file() or not protocol_path.is_file():
        raise FileNotFoundError("U6b frozen split/protocol is missing")
    if sha256_file(split_path) != EXPECTED_SPLIT_SHA256:
        raise ValueError("U6b split SHA differs from the frozen selection")
    split = json.loads(split_path.read_text())
    protocol = json.loads(protocol_path.read_text())
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
    return split, protocol


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
    *, split_path: Path, protocol_path: Path, ca1m_root: Path, arkit_root: Path
) -> dict:
    split, _ = validate_frozen_inputs(split_path, protocol_path)
    raw_csv = arkit_root / "raw" / "raw_train_val_splits.csv"
    if not raw_csv.is_file():
        raise FileNotFoundError(f"ARKitScenes raw split CSV missing: {raw_csv}")
    raw_index = load_raw_index(raw_csv)
    entries: list[dict] = []
    for item in split["confirmatoryVideos"]:
        video = str(item["videoId"])
        visit = str(item["visitId"])
        found = raw_index.get(video)
        expected = (visit, "Validation")
        if found != expected:
            raise ValueError(
                f"ARKitScenes metadata mismatch for {video}: expected {expected}, found {found}"
            )
        entries.append(asset_state(ca1m_root, arkit_root, video, visit))
    contaminated = [entry["videoId"] for entry in entries if entry["preexisting"]]
    clean = not contaminated
    return {
        "schemaVersion": 1,
        "study": STUDY_ID,
        "stage": "U6b-confirmatory-acquisition-plan",
        "createdAtUtc": utc_now(),
        "status": "clean-before-u6b-acquisition" if clean else "blocked-preexisting-u6b-assets",
        "canExecuteAcquisition": clean,
        "networkAccessPerformed": False,
        "datasetMutationPerformed": False,
        "splitSha256": sha256_file(split_path),
        "protocolSha256": sha256_file(protocol_path),
        "arkitRawSplitSha256": sha256_file(raw_csv),
        "ca1mRoot": str(ca1m_root.resolve()),
        "arkitRoot": str(arkit_root.resolve()),
        "preexistingVideoIds": contaminated,
        "entries": entries,
        "failurePolicy": "Any preexisting selected U6b asset blocks confirmatory acquisition. Do not replace a room or delete evidence to manufacture a clean boundary.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--ca1m-root", type=Path, required=True)
    parser.add_argument("--arkit-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("U6b acquisition plan already exists; will not overwrite")
    plan = build_plan(
        split_path=args.split,
        protocol_path=args.protocol,
        ca1m_root=args.ca1m_root,
        arkit_root=args.arkit_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    print(json.dumps(plan, sort_keys=True))
    return 0 if plan["canExecuteAcquisition"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
