#!/usr/bin/env python3
"""Acquire the frozen U6b confirmatory assets after the clean acquisition plan."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import zipfile


STUDY_ID = "metric-uncertainty-u6b-opacity-visibility-confirmatory-v1"
EXPECTED_PLAN_SHA256 = "dbb0e4ccc9214c103cd3ba115f9bbbcbd088922b8293a260100759b3a390c5ed"
EXPECTED_SPLIT_SHA256 = "d22366afd77d3407e53d5152d313522d559ee57e9ec995d96102c299dc55f5ff"
EXPECTED_PROTOCOL_SHA256 = "0c58590d7c71c24797d583bd2681c1fc8994028d9b188b1fbe5fb5a4c4e1b3e3"
EXPECTED_METADATA_EVIDENCE_SHA256 = "bc855db7fa6666dcab7997434949fd8d89027d3b9c3fdbda8a30896e80d0742b"
EXPECTED_VIDEOS = [
    ("42898811", "434650"),
    ("45261121", "466628"),
    ("47895341", "472297"),
    ("47332915", "469249"),
    ("47331971", "470821"),
]
CA1M_URL_TEMPLATE = "https://ml-site.cdn-apple.com/datasets/ca1m/val/ca1m-val-{video}.tar"
ARKIT_RAW_URL_TEMPLATE = (
    "https://docs-assets.developer.apple.com/ml-research/datasets/arkitscenes/v1/"
    "raw/Validation/{video}/{asset}.zip"
)
SIDECARS = ("confidence", "lowres_depth")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def birth_time(path: Path) -> str | None:
    if not path.exists():
        return None
    value = getattr(path.stat(), "st_birthtime", None)
    if value is None:
        return None
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def ca1m_url(video: str) -> str:
    return CA1M_URL_TEMPLATE.format(video=video)


def sidecar_url(video: str, asset: str) -> str:
    if asset not in SIDECARS:
        raise ValueError(f"unsupported U6b sidecar: {asset}")
    return ARKIT_RAW_URL_TEMPLATE.format(video=video, asset=asset)


def validate_plan_payload(plan: dict) -> None:
    if plan.get("study") != STUDY_ID:
        raise ValueError("U6b acquisition plan study differs")
    if plan.get("status") != "clean-before-u6b-acquisition":
        raise ValueError("U6b acquisition requires a clean pre-acquisition plan")
    if plan.get("canExecuteAcquisition") is not True:
        raise ValueError("U6b acquisition plan does not authorize acquisition")
    if plan.get("networkAccessPerformed") is not False:
        raise ValueError("U6b plan unexpectedly records network access")
    if plan.get("datasetMutationPerformed") is not False:
        raise ValueError("U6b plan unexpectedly records dataset mutation")
    if plan.get("preexistingVideoIds") != []:
        raise ValueError("U6b plan records preexisting selected assets")
    if plan.get("splitSha256") != EXPECTED_SPLIT_SHA256:
        raise ValueError("U6b plan split SHA differs")
    if plan.get("protocolSha256") != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("U6b plan protocol SHA differs")
    if plan.get("publicMetadataEvidenceSha256") != EXPECTED_METADATA_EVIDENCE_SHA256:
        raise ValueError("U6b plan public metadata evidence SHA differs")
    pairs = [
        (str(entry["videoId"]), str(entry["visitId"]))
        for entry in plan.get("entries", [])
    ]
    if pairs != EXPECTED_VIDEOS:
        raise ValueError("U6b plan scene membership/order differs")
    if any(entry.get("preexisting") is not False for entry in plan["entries"]):
        raise ValueError("U6b plan contains a preexisting selected asset")


def load_frozen_plan(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"U6b acquisition plan missing: {path}")
    digest = sha256_file(path)
    if digest != EXPECTED_PLAN_SHA256:
        raise ValueError(f"unexpected U6b acquisition plan SHA: {digest}")
    plan = json.loads(path.read_text())
    validate_plan_payload(plan)
    return plan


def asset_paths(ca1m_root: Path, arkit_root: Path, video: str) -> dict[str, Path]:
    raw_root = arkit_root / "raw" / "Validation" / video
    return {
        "ca1mArchive": ca1m_root / f"ca1m-val-{video}.tar",
        "ca1mPartial": ca1m_root / f"ca1m-val-{video}.tar.part",
        "rawRoot": raw_root,
        "confidenceZip": raw_root / "confidence.zip",
        "confidencePartial": raw_root / "confidence.zip.part",
        "confidenceDirectory": raw_root / "confidence",
        "lowresDepthZip": raw_root / "lowres_depth.zip",
        "lowresDepthPartial": raw_root / "lowres_depth.zip.part",
        "lowresDepthDirectory": raw_root / "lowres_depth",
    }


def png_count(path: Path) -> int:
    if not path.is_dir():
        return 0
    return len(list(path.glob("*.png")))


def download_with_resume(url: str, final_path: Path) -> None:
    if final_path.is_file():
        return
    final_path.parent.mkdir(parents=True, exist_ok=True)
    partial = final_path.with_suffix(final_path.suffix + ".part")
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
    os.replace(partial, final_path)


def validate_ca1m_tar(path: Path) -> int:
    with tarfile.open(path, "r") as archive:
        members = archive.getmembers()
        if not members:
            raise ValueError(f"CA-1M archive is empty: {path}")
        names = [member.name.lower() for member in members]
        required = {
            "wideDepth": any("wide/depth" in name for name in names),
            "gtDepth": any("gt/depth" in name for name in names),
            "gtPose": any("gt/rt" in name for name in names),
        }
        if not all(required.values()):
            raise ValueError(f"CA-1M archive lacks required groups {required}: {path}")
        return len(members)


def extract_sidecar(zip_path: Path, output_root: Path, expected_directory: Path) -> int:
    if not zip_path.is_file():
        raise FileNotFoundError(f"sidecar zip missing: {zip_path}")
    with zipfile.ZipFile(zip_path, "r") as archive:
        bad = archive.testzip()
        if bad is not None:
            raise ValueError(f"corrupt zip member {bad} in {zip_path}")
        for member in archive.infolist():
            destination = (output_root / member.filename).resolve()
            if output_root.resolve() not in destination.parents and destination != output_root.resolve():
                raise ValueError(f"unsafe zip member path in {zip_path}: {member.filename}")
        archive.extractall(output_root)
    count = png_count(expected_directory)
    if count <= 0:
        raise ValueError(f"sidecar extraction produced no PNGs: {expected_directory}")
    return count


def acquire_scene(ca1m_root: Path, arkit_root: Path, video: str, visit: str) -> dict:
    paths = asset_paths(ca1m_root, arkit_root, video)
    start_state = {
        "ca1mArchivePresentAtExecuteEntry": paths["ca1mArchive"].is_file(),
        "ca1mPartialPresentAtExecuteEntry": paths["ca1mPartial"].exists(),
        "confidenceZipPresentAtExecuteEntry": paths["confidenceZip"].is_file(),
        "confidencePartialPresentAtExecuteEntry": paths["confidencePartial"].exists(),
        "confidencePngCountAtExecuteEntry": png_count(paths["confidenceDirectory"]),
        "lowresDepthZipPresentAtExecuteEntry": paths["lowresDepthZip"].is_file(),
        "lowresDepthPartialPresentAtExecuteEntry": paths["lowresDepthPartial"].exists(),
        "lowresDepthPngCountAtExecuteEntry": png_count(paths["lowresDepthDirectory"]),
    }

    download_with_resume(ca1m_url(video), paths["ca1mArchive"])
    ca1m_members = validate_ca1m_tar(paths["ca1mArchive"])

    sidecar_counts: dict[str, int] = {}
    for asset in SIDECARS:
        zip_key = "confidenceZip" if asset == "confidence" else "lowresDepthZip"
        dir_key = "confidenceDirectory" if asset == "confidence" else "lowresDepthDirectory"
        download_with_resume(sidecar_url(video, asset), paths[zip_key])
        sidecar_counts[asset] = extract_sidecar(
            paths[zip_key], paths["rawRoot"], paths[dir_key]
        )

    return {
        "videoId": video,
        "visitId": visit,
        **start_state,
        "ca1mArchive": str(paths["ca1mArchive"].resolve()),
        "ca1mArchiveSha256": sha256_file(paths["ca1mArchive"]),
        "ca1mArchiveBytes": paths["ca1mArchive"].stat().st_size,
        "ca1mArchiveMemberCount": ca1m_members,
        "ca1mArchiveBirthTimeUtc": birth_time(paths["ca1mArchive"]),
        "confidenceZip": str(paths["confidenceZip"].resolve()),
        "confidenceZipSha256": sha256_file(paths["confidenceZip"]),
        "confidenceZipBytes": paths["confidenceZip"].stat().st_size,
        "confidencePngCount": sidecar_counts["confidence"],
        "lowresDepthZip": str(paths["lowresDepthZip"].resolve()),
        "lowresDepthZipSha256": sha256_file(paths["lowresDepthZip"]),
        "lowresDepthZipBytes": paths["lowresDepthZip"].stat().st_size,
        "lowresDepthPngCount": sidecar_counts["lowres_depth"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--ca1m-root", type=Path, required=True)
    parser.add_argument("--arkit-root", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()

    if args.ledger.exists():
        raise ValueError("U6b acquisition ledger already exists; will not overwrite")

    plan = load_frozen_plan(args.plan.resolve())
    ca1m_root = args.ca1m_root.resolve()
    arkit_root = args.arkit_root.resolve()

    started = utc_now()
    completed_entries = []
    for video, visit in EXPECTED_VIDEOS:
        print(f"Acquiring U6b {video} visit {visit}", flush=True)
        completed_entries.append(acquire_scene(ca1m_root, arkit_root, video, visit))

    payload = {
        "schemaVersion": 1,
        "study": STUDY_ID,
        "stage": "U6b-confirmatory-asset-acquisition",
        "status": "acquired-after-frozen-clean-plan",
        "startedAtUtc": started,
        "completedAtUtc": utc_now(),
        "planSha256": EXPECTED_PLAN_SHA256,
        "splitSha256": EXPECTED_SPLIT_SHA256,
        "protocolSha256": EXPECTED_PROTOCOL_SHA256,
        "publicMetadataEvidenceSha256": EXPECTED_METADATA_EVIDENCE_SHA256,
        "selectedAssetsAbsentAtFrozenPlan": True,
        "recoveryPolicy": "If execution is interrupted before this ledger is written, rerunning with the same exact frozen plan may resume .part downloads or revalidate files created by this execution. The selected scene set and URLs may not change.",
        "entries": completed_entries,
    }
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.ledger.with_suffix(args.ledger.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, args.ledger)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
