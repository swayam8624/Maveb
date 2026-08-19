#!/usr/bin/env python3
"""Acquire the frozen ARKitScenes split used by Maveb's metric-uncertainty study.

This wrapper never redistributes ARKitScenes. It validates Maveb's preregistered split against a
user-supplied clone of Apple's official ARKitScenes repository, then delegates download to Apple's
`download_data.py`. Without --execute it only prints the exact download plan.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Iterable


REQUIRED_RAW_ASSETS = (
    "mesh",
    "confidence",
    "lowres_depth",
    "lowres_wide.traj",
    "lowres_wide",
    "lowres_wide_intrinsics",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_split(path: Path) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    payload = json.loads(raw)
    if payload.get("schemaVersion") != 1:
        raise ValueError("unsupported uncertainty split schema")
    if payload.get("frozen") is not True:
        raise ValueError("public split must be frozen before U1 acquisition")
    return payload, raw


def selected_scenes(payload: dict) -> list[str]:
    calibration = [str(v) for v in payload.get("calibrationScenes", [])]
    held_out = [str(v) for v in payload.get("heldOutScenes", [])]
    if len(calibration) < int(payload.get("rules", {}).get("minimumCalibrationScenes", 3)):
        raise ValueError("frozen split has too few calibration scenes")
    if len(held_out) < int(payload.get("rules", {}).get("minimumHeldOutScenes", 5)):
        raise ValueError("frozen split has too few held-out scenes")
    overlap = sorted(set(calibration) & set(held_out))
    if overlap:
        raise ValueError(f"calibration/held-out scene leakage: {', '.join(overlap)}")
    return calibration + held_out


def validate_split(payload: dict) -> None:
    scenes = selected_scenes(payload)
    metadata = payload.get("sceneMetadata")
    if not isinstance(metadata, dict):
        raise ValueError("frozen split is missing sceneMetadata")

    visits: dict[str, str] = {}
    for scene in scenes:
        entry = metadata.get(scene)
        if not isinstance(entry, dict):
            raise ValueError(f"missing scene metadata: {scene}")
        video_id = str(entry.get("videoId", ""))
        visit_id = str(entry.get("visitId", ""))
        fold = str(entry.get("fold", ""))
        role = str(entry.get("role", ""))
        if scene != f"arkitscenes-{video_id}":
            raise ValueError(f"scene/video identity mismatch: {scene}")
        expected_role = "calibration" if scene in payload["calibrationScenes"] else "held-out"
        expected_fold = "Training" if expected_role == "calibration" else "Validation"
        if role != expected_role or fold != expected_fold:
            raise ValueError(f"role/fold mismatch for {scene}")
        if not visit_id or visit_id == "NA":
            raise ValueError(f"selected research scene must have a visit_id: {scene}")
        previous = visits.get(visit_id)
        if previous is not None:
            raise ValueError(f"visit-level leakage between {previous} and {scene}")
        visits[visit_id] = scene


def load_official_split(path: Path) -> dict[str, tuple[str, str]]:
    rows: dict[str, tuple[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["video_id", "visit_id", "fold"]:
            raise ValueError("unexpected ARKitScenes raw split CSV columns")
        for row in reader:
            video_id = str(row["video_id"]).strip()
            if video_id in rows:
                raise ValueError(f"duplicate video_id in official split: {video_id}")
            rows[video_id] = (str(row["visit_id"]).strip(), str(row["fold"]).strip())
    return rows


def validate_against_official_split(payload: dict, official_rows: dict[str, tuple[str, str]]) -> None:
    for scene in selected_scenes(payload):
        entry = payload["sceneMetadata"][scene]
        video_id = str(entry["videoId"])
        actual = official_rows.get(video_id)
        if actual is None:
            raise ValueError(f"selected video_id is absent from official raw split: {video_id}")
        expected = (str(entry["visitId"]), str(entry["fold"]))
        if actual != expected:
            raise ValueError(
                f"official split mismatch for {video_id}: expected visit/fold {expected}, got {actual}"
            )


def download_commands(
    payload: dict,
    *,
    arkit_repo: Path,
    download_dir: Path,
) -> list[list[str]]:
    downloader = arkit_repo / "download_data.py"
    commands: list[list[str]] = []
    for fold in ("Training", "Validation"):
        video_ids = [
            str(payload["sceneMetadata"][scene]["videoId"])
            for scene in selected_scenes(payload)
            if payload["sceneMetadata"][scene]["fold"] == fold
        ]
        if not video_ids:
            continue
        commands.append(
            [
                sys.executable,
                str(downloader),
                "raw",
                "--split",
                fold,
                "--video_id",
                *video_ids,
                "--download_dir",
                str(download_dir),
                "--raw_dataset_assets",
                *REQUIRED_RAW_ASSETS,
            ]
        )
    return commands


def expected_scene_root(download_dir: Path, entry: dict) -> Path:
    return download_dir / "raw" / str(entry["fold"]) / str(entry["videoId"])


def missing_scene_assets(root: Path, video_id: str) -> list[str]:
    required = (
        root / "confidence",
        root / "lowres_depth",
        root / "lowres_wide",
        root / "lowres_wide_intrinsics",
        root / "lowres_wide.traj",
        root / f"{video_id}_3dod_mesh.ply",
    )
    return [str(path) for path in required if not path.exists()]


def acquisition_status(payload: dict, download_dir: Path) -> list[dict]:
    status = []
    for scene in selected_scenes(payload):
        entry = payload["sceneMetadata"][scene]
        root = expected_scene_root(download_dir, entry)
        missing = missing_scene_assets(root, str(entry["videoId"]))
        status.append(
            {
                "scene": scene,
                "role": entry["role"],
                "fold": entry["fold"],
                "visitId": entry["visitId"],
                "root": str(root.resolve()),
                "ready": not missing,
                "missing": missing,
            }
        )
    return status


def run_commands(commands: Iterable[list[str]], cwd: Path) -> None:
    for command in commands:
        subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--split",
        type=Path,
        default=root / "benchmarks/experiments/metric-uncertainty-public-split-v1.json",
    )
    parser.add_argument("--arkitscenes-repo", type=Path, required=True)
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", help="actually invoke Apple's downloader")
    parser.add_argument("--ledger", type=Path, help="optional acquisition ledger JSON")
    args = parser.parse_args()

    try:
        payload, split_bytes = load_split(args.split.resolve())
        validate_split(payload)

        arkit_repo = args.arkitscenes_repo.resolve()
        downloader = arkit_repo / "download_data.py"
        official_csv = arkit_repo / "raw/raw_train_val_splits.csv"
        if not downloader.is_file() or not official_csv.is_file():
            raise ValueError(
                "--arkitscenes-repo must be a clone containing download_data.py and "
                "raw/raw_train_val_splits.csv"
            )
        official_rows = load_official_split(official_csv)
        validate_against_official_split(payload, official_rows)

        download_dir = args.download_dir.resolve()
        commands = download_commands(payload, arkit_repo=arkit_repo, download_dir=download_dir)
        if args.execute:
            run_commands(commands, arkit_repo)

        status = acquisition_status(payload, download_dir)
        ledger = {
            "schemaVersion": 1,
            "study": "metric-uncertainty-v1",
            "splitId": payload["id"],
            "splitSha256": sha256_bytes(split_bytes),
            "officialSplitCsv": str(official_csv),
            "officialSplitCsvSha256": hashlib.sha256(official_csv.read_bytes()).hexdigest(),
            "requiredRawAssets": list(REQUIRED_RAW_ASSETS),
            "executeRequested": args.execute,
            "commands": [shlex.join(command) for command in commands],
            "scenes": status,
            "readyScenes": sum(1 for item in status if item["ready"]),
            "totalScenes": len(status),
        }
        if args.ledger:
            args.ledger.parent.mkdir(parents=True, exist_ok=True)
            args.ledger.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"ok": True, **ledger}, sort_keys=True))
        return 0 if (not args.execute or all(item["ready"] for item in status)) else 3
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"acquire_arkit_uncertainty: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
