#!/usr/bin/env python3
"""Acquire the frozen U3b confirmatory CA-1M + ARKitScenes assets with provenance gates.

The plan stage is intentionally read-only and records whether any confirmatory asset already exists.
The execute stage requires a clean plan ledger showing that all selected confirmatory assets were
absent before acquisition. This prevents a repeat of the U2 acquisition-timing ambiguity.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

EXPECTED_SPLIT_SHA256 = "f7269b595bafe5e50d975b3026a958b1a4b0ef2bcc695f4494d161f8aa285e56"
EXPECTED_MODEL_SHA256 = "744cdfce9763f5d2ecd9c9a4e53385f66d8bba7cbc047e11729189053a85e17a"
EXPECTED_STUDY_ID = "metric-uncertainty-u3b-relative-confidence-transfer-v1"
CA1M_URL_TEMPLATE = "https://ml-site.cdn-apple.com/datasets/ca1m/val/ca1m-val-{video}.tar"
ASSETS = ("confidence", "lowres_depth")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def load_json_with_sha(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


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


def validate_protocol(split_path: Path, protocol_path: Path) -> tuple[dict, dict, str, str]:
    split, split_sha = load_json_with_sha(split_path)
    protocol, protocol_sha = load_json_with_sha(protocol_path)

    if split_sha != EXPECTED_SPLIT_SHA256:
        raise ValueError(f"unexpected U3b split SHA: {split_sha}")
    if split.get("study") != EXPECTED_STUDY_ID:
        raise ValueError("split study id is not the frozen U3b study")
    if split.get("selectionStatus") != "frozen-before-confirmatory-asset-acquisition":
        raise ValueError("split is not marked frozen before acquisition")
    if protocol.get("id") != EXPECTED_STUDY_ID or protocol.get("frozen") is not True:
        raise ValueError("U3b protocol is not the frozen confirmatory protocol")
    if protocol.get("status") != "preregistered-before-confirmatory-asset-acquisition":
        raise ValueError("U3b protocol status does not preserve pre-acquisition preregistration")
    if protocol.get("confirmatorySplit", {}).get("sha256") != split_sha:
        raise ValueError("protocol does not bind the exact current confirmatory split SHA")
    if protocol.get("frozenPredictiveModel", {}).get("sha256") != EXPECTED_MODEL_SHA256:
        raise ValueError("protocol does not bind the frozen U1b model")

    split_pairs = [
        (str(item["videoId"]), str(item["visitId"]))
        for item in split.get("confirmatoryVideos", [])
    ]
    protocol_pairs = [
        (str(item["videoId"]), str(item["visitId"]))
        for item in protocol.get("confirmatorySplit", {}).get("videos", [])
    ]
    if len(split_pairs) != 5 or split_pairs != protocol_pairs:
        raise ValueError("protocol/split confirmatory scene membership differs")
    if len({visit for _, visit in split_pairs}) != len(split_pairs):
        raise ValueError("confirmatory visits are not distinct")

    return split, protocol, split_sha, protocol_sha


def birth_time(path: Path) -> str | None:
    if not path.exists():
        return None
    stat = path.stat()
    value = getattr(stat, "st_birthtime", None)
    if value is None:
        return None
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def asset_state(ca1m_root: Path, arkit_root: Path, video: str, visit: str) -> dict:
    tar_path = ca1m_root / f"ca1m-val-{video}.tar"
    part_path = tar_path.with_suffix(tar_path.suffix + ".part")
    root = arkit_root / "raw" / "Validation" / video
    confidence = root / "confidence"
    lowres_depth = root / "lowres_depth"
    confidence_zip = root / "confidence.zip"
    lowres_zip = root / "lowres_depth.zip"

    confidence_pngs = sorted(confidence.glob("*.png")) if confidence.is_dir() else []
    lowres_pngs = sorted(lowres_depth.glob("*.png")) if lowres_depth.is_dir() else []
    preexisting = bool(
        tar_path.exists()
        or part_path.exists()
        or confidence_pngs
        or lowres_pngs
        or confidence_zip.exists()
        or lowres_zip.exists()
    )
    return {
        "videoId": video,
        "visitId": visit,
        "ca1mArchive": str(tar_path.resolve()),
        "ca1mPartial": str(part_path.resolve()),
        "arkitScenesRoot": str(root.resolve()),
        "confidenceDirectory": str(confidence.resolve()),
        "lowresDepthDirectory": str(lowres_depth.resolve()),
        "confidenceZip": str(confidence_zip.resolve()),
        "lowresDepthZip": str(lowres_zip.resolve()),
        "preexisting": preexisting,
        "ca1mArchiveAlreadyPresent": tar_path.is_file(),
        "ca1mPartialAlreadyPresent": part_path.exists(),
        "confidencePngCountBefore": len(confidence_pngs),
        "lowresDepthPngCountBefore": len(lowres_pngs),
        "confidenceZipAlreadyPresent": confidence_zip.is_file(),
        "lowresDepthZipAlreadyPresent": lowres_zip.is_file(),
        "ca1mArchiveBirthTimeUtcBefore": birth_time(tar_path),
        "confidenceDirectoryBirthTimeUtcBefore": birth_time(confidence),
        "lowresDepthDirectoryBirthTimeUtcBefore": birth_time(lowres_depth),
    }


def validate_raw_index(arkit_repo: Path, entries: list[dict]) -> str:
    raw_csv = arkit_repo / "raw" / "raw_train_val_splits.csv"
    if not raw_csv.is_file():
        raise ValueError("ARKitScenes repo is missing raw/raw_train_val_splits.csv")
    index = load_raw_index(raw_csv)
    for entry in entries:
        indexed = index.get(entry["videoId"])
        expected = (entry["visitId"], "Validation")
        if indexed != expected:
            raise ValueError(
                f"ARKitScenes metadata mismatch for {entry['videoId']}: "
                f"expected {expected}, found {indexed}"
            )
    return sha256_file(raw_csv)


def validate_tar(path: Path) -> int:
    with tarfile.open(path, "r") as archive:
        members = archive.getmembers()
        if not members:
            raise ValueError(f"downloaded CA-1M archive is empty: {path}")
        required_suffixes = ("wide/depth.png", "gt/depth.png", "gt/RT.txt")
        names = [member.name.lower() for member in members]
        # CA-1M member names vary in exact extension/case across releases; require the
        # conceptual source groups rather than one hard-coded filename.
        has_wide_depth = any("wide/depth" in name for name in names)
        has_gt_depth = any("gt/depth" in name for name in names)
        has_gt_pose = any("gt/rt" in name for name in names)
        if not (has_wide_depth and has_gt_depth and has_gt_pose):
            raise ValueError(
                f"CA-1M archive lacks expected wide/depth, gt/depth or gt/RT members: {path}"
            )
        _ = required_suffixes
        return len(members)


def download_ca1m(entry: dict) -> None:
    target = Path(entry["ca1mArchive"])
    partial = Path(entry["ca1mPartial"])
    target.parent.mkdir(parents=True, exist_ok=True)
    url = CA1M_URL_TEMPLATE.format(video=entry["videoId"])
    command = [
        "curl",
        "-fL",
        "--retry",
        "4",
        "--retry-delay",
        "2",
        "-C",
        "-",
        "-o",
        str(partial),
        url,
    ]
    subprocess.run(command, check=True)
    os.replace(partial, target)


def download_sidecars(arkit_repo: Path, arkit_root: Path, videos: list[str]) -> None:
    downloader = arkit_repo / "download_data.py"
    if not downloader.is_file():
        raise ValueError("ARKitScenes repo is missing download_data.py")
    command = [
        sys.executable,
        str(downloader),
        "raw",
        "--split",
        "Validation",
        "--video_id",
        *videos,
        "--download_dir",
        str(arkit_root),
        "--raw_dataset_assets",
        *ASSETS,
        "--keep_zip",
    ]
    subprocess.run(command, cwd=arkit_repo, check=True)


def execute(plan: dict, arkit_repo: Path, ca1m_root: Path, arkit_root: Path) -> dict:
    if plan.get("status") != "clean-confirmatory-assets-absent":
        raise ValueError("execute requires a clean plan ledger with all confirmatory assets absent")
    if not plan.get("allConfirmatoryAssetsAbsentBeforePlan"):
        raise ValueError("one or more confirmatory assets existed before the plan")

    entries = plan["entries"]
    start = utc_now()
    for entry in entries:
        download_ca1m(entry)
    download_sidecars(arkit_repo, arkit_root, [entry["videoId"] for entry in entries])

    completed_entries = []
    for original in entries:
        video = original["videoId"]
        visit = original["visitId"]
        current = asset_state(ca1m_root, arkit_root, video, visit)
        tar_path = Path(current["ca1mArchive"])
        confidence = Path(current["confidenceDirectory"])
        lowres_depth = Path(current["lowresDepthDirectory"])
        confidence_pngs = sorted(confidence.glob("*.png")) if confidence.is_dir() else []
        lowres_pngs = sorted(lowres_depth.glob("*.png")) if lowres_depth.is_dir() else []
        if not tar_path.is_file() or not confidence_pngs or not lowres_pngs:
            raise ValueError(f"confirmatory acquisition incomplete for video {video}")
        member_count = validate_tar(tar_path)
        completed_entries.append({
            **original,
            "ca1mArchiveSha256": sha256_file(tar_path),
            "ca1mArchiveBytes": tar_path.stat().st_size,
            "ca1mArchiveMemberCount": member_count,
            "ca1mArchiveBirthTimeUtcAfter": birth_time(tar_path),
            "confidencePngCountAfter": len(confidence_pngs),
            "lowresDepthPngCountAfter": len(lowres_pngs),
            "confidenceDirectoryBirthTimeUtcAfter": birth_time(confidence),
            "lowresDepthDirectoryBirthTimeUtcAfter": birth_time(lowres_depth),
        })

    return {
        "schemaVersion": 1,
        "study": EXPECTED_STUDY_ID,
        "stage": "U3b-confirmatory-asset-acquisition",
        "status": "acquired-after-clean-preregistered-plan",
        "startedAtUtc": start,
        "completedAtUtc": utc_now(),
        "splitSha256": plan["splitSha256"],
        "protocolSha256": plan["protocolSha256"],
        "rawIndexSha256": plan["rawIndexSha256"],
        "planLedgerSha256": plan["selfSha256WithoutSelfField"],
        "allConfirmatoryAssetsAbsentBeforePlan": True,
        "entries": completed_entries,
    }


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("plan", "execute"), required=True)
    parser.add_argument(
        "--split",
        type=Path,
        default=repo_root / "benchmarks/experiments/metric-uncertainty-u3b-confirmatory-split-v1.json",
    )
    parser.add_argument(
        "--protocol",
        type=Path,
        default=repo_root / "benchmarks/experiments/metric-uncertainty-u3b-relative-confidence-transfer-v1.json",
    )
    parser.add_argument("--arkitscenes-repo", type=Path, required=True)
    parser.add_argument("--ca1m-root", type=Path, required=True)
    parser.add_argument("--arkitscenes-root", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--plan-ledger", type=Path)
    args = parser.parse_args()

    try:
        split, _protocol, split_sha, protocol_sha = validate_protocol(
            args.split.resolve(), args.protocol.resolve()
        )
        arkit_repo = args.arkitscenes_repo.resolve()
        ca1m_root = args.ca1m_root.resolve()
        arkit_root = args.arkitscenes_root.resolve()
        selected = [
            (str(item["videoId"]), str(item["visitId"]))
            for item in split["confirmatoryVideos"]
        ]
        entries = [asset_state(ca1m_root, arkit_root, video, visit) for video, visit in selected]
        raw_index_sha = validate_raw_index(arkit_repo, entries)

        if args.stage == "plan":
            all_absent = not any(entry["preexisting"] for entry in entries)
            payload = {
                "schemaVersion": 1,
                "study": EXPECTED_STUDY_ID,
                "stage": "U3b-confirmatory-acquisition-plan",
                "status": (
                    "clean-confirmatory-assets-absent"
                    if all_absent
                    else "blocked-confirmatory-assets-preexisting"
                ),
                "plannedAtUtc": utc_now(),
                "splitSha256": split_sha,
                "protocolSha256": protocol_sha,
                "rawIndexSha256": raw_index_sha,
                "allConfirmatoryAssetsAbsentBeforePlan": all_absent,
                "entries": entries,
            }
            raw_without_self = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
            payload["selfSha256WithoutSelfField"] = hashlib.sha256(raw_without_self).hexdigest()
            write_json_atomic(args.ledger.resolve(), payload)
            print(json.dumps(payload, sort_keys=True))
            return 0 if all_absent else 3

        if args.plan_ledger is None:
            raise ValueError("--stage execute requires --plan-ledger")
        plan, plan_file_sha = load_json_with_sha(args.plan_ledger.resolve())
        if plan.get("splitSha256") != split_sha or plan.get("protocolSha256") != protocol_sha:
            raise ValueError("plan ledger no longer matches the frozen split/protocol")
        # Verify the plan content was not hand-edited after generation. The self field hashes
        # the canonical payload before that field was appended; the file SHA is recorded too.
        plan_without_self = dict(plan)
        expected_self = plan_without_self.pop("selfSha256WithoutSelfField", None)
        actual_self = hashlib.sha256(
            (json.dumps(plan_without_self, indent=2, sort_keys=True) + "\n").encode()
        ).hexdigest()
        if expected_self != actual_self:
            raise ValueError("plan ledger self-hash mismatch")

        result = execute(plan, arkit_repo, ca1m_root, arkit_root)
        result["planLedgerFileSha256"] = plan_file_sha
        write_json_atomic(args.ledger.resolve(), result)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError, json.JSONDecodeError) as exc:
        print(f"acquire_u3b_confirmatory_assets: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
