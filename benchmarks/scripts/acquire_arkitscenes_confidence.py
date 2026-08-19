#!/usr/bin/env python3
"""Acquire ARKitScenes raw confidence sidecars for the frozen uncertainty study.

Default role is calibration. Held-out confidence is not downloaded unless the caller explicitly
requests `--role held-out` after the calibration model has been frozen. The wrapper validates every
video/fold/visit against Apple's raw split CSV and delegates bytes to Apple's official
download_data.py using only the `confidence` raw asset.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_split(path: Path) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    payload = json.loads(raw)
    if payload.get("schemaVersion") != 1 or payload.get("frozen") is not True:
        raise ValueError("confidence acquisition requires the frozen schema-v1 split")
    source = payload.get("source", {})
    if source.get("dataset") != "CA-1M / Cubify Anything":
        raise ValueError("split does not use CA-1M ground truth")
    if source.get("confidenceDataset") != "ARKitScenes raw":
        raise ValueError("split does not require ARKitScenes raw confidence")
    return payload, raw


def load_raw_index(path: Path) -> dict[str, tuple[str, str]]:
    rows: dict[str, tuple[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        required = {"video_id", "visit_id", "fold"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError("ARKitScenes raw split CSV lacks video_id/visit_id/fold")
        for row in reader:
            video = str(row["video_id"]).strip()
            visit = str(row["visit_id"]).strip()
            fold = str(row["fold"]).strip()
            if video:
                rows[video] = (visit, fold)
    if not rows:
        raise ValueError("ARKitScenes raw split CSV is empty")
    return rows


def scenes_for_role(payload: dict, role: str) -> list[str]:
    if role == "calibration":
        return [str(value) for value in payload["calibrationScenes"]]
    if role == "held-out":
        return [str(value) for value in payload["heldOutScenes"]]
    return [str(value) for value in payload["calibrationScenes"] + payload["heldOutScenes"]]


def plan(payload: dict, raw_index: dict[str, tuple[str, str]], output_root: Path, role: str) -> list[dict]:
    entries = []
    for scene in scenes_for_role(payload, role):
        metadata = payload["sceneMetadata"][scene]
        video = str(metadata["videoId"])
        visit = str(metadata["visitId"])
        fold = str(metadata["arkitFold"])
        indexed = raw_index.get(video)
        if indexed is None:
            raise ValueError(f"{scene} is absent from ARKitScenes raw split CSV")
        indexed_visit, indexed_fold = indexed
        if indexed_visit != visit or indexed_fold != fold:
            raise ValueError(
                f"ARKitScenes metadata mismatch for {scene}: expected visit/fold {visit}/{fold}, "
                f"found {indexed_visit}/{indexed_fold}"
            )
        confidence = output_root / "raw" / fold / video / "confidence"
        entries.append(
            {
                "scene": scene,
                "role": metadata["role"],
                "videoId": video,
                "visitId": visit,
                "fold": fold,
                "confidenceDirectory": str(confidence.resolve()),
                "alreadyPresent": confidence.is_dir() and any(confidence.glob("*.png")),
            }
        )
    return entries


def execute_download(arkit_repo: Path, output_root: Path, entries: list[dict]) -> None:
    by_fold: dict[str, list[str]] = {}
    for entry in entries:
        if not entry["alreadyPresent"]:
            by_fold.setdefault(str(entry["fold"]), []).append(str(entry["videoId"]))
    for fold, video_ids in sorted(by_fold.items()):
        command = [
            sys.executable,
            str(arkit_repo / "download_data.py"),
            "raw",
            "--split",
            fold,
            "--video_id",
            *video_ids,
            "--download_dir",
            str(output_root),
            "--raw_dataset_assets",
            "confidence",
            "--keep_zip",
        ]
        subprocess.run(command, cwd=arkit_repo, check=True)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--split",
        type=Path,
        default=repo_root / "benchmarks/experiments/metric-uncertainty-public-split-v1.json",
    )
    parser.add_argument("--arkitscenes-repo", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--role", choices=("calibration", "held-out", "all"), default="calibration")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--ledger", type=Path)
    args = parser.parse_args()

    try:
        payload, split_bytes = load_split(args.split.resolve())
        arkit_repo = args.arkitscenes_repo.resolve()
        downloader = arkit_repo / "download_data.py"
        raw_csv = arkit_repo / "raw/raw_train_val_splits.csv"
        if not downloader.is_file() or not raw_csv.is_file():
            raise ValueError(
                "--arkitscenes-repo must be an apple/ARKitScenes clone containing download_data.py "
                "and raw/raw_train_val_splits.csv"
            )
        raw_index = load_raw_index(raw_csv)
        output_root = args.output_dir.resolve()
        entries = plan(payload, raw_index, output_root, args.role)
        if args.execute:
            execute_download(arkit_repo, output_root, entries)
            for entry in entries:
                confidence = Path(entry["confidenceDirectory"])
                pngs = sorted(confidence.glob("*.png")) if confidence.is_dir() else []
                entry["downloaded"] = bool(pngs)
                entry["confidencePngCount"] = len(pngs)
            if not all(entry.get("downloaded") for entry in entries):
                raise ValueError("one or more frozen confidence sidecars were not acquired")

        ledger = {
            "schemaVersion": 1,
            "study": "metric-uncertainty-v1",
            "asset": "ARKitScenes raw confidence",
            "role": args.role,
            "splitId": payload["id"],
            "splitRevision": payload.get("revision"),
            "splitSha256": hashlib.sha256(split_bytes).hexdigest(),
            "rawIndexSha256": sha256_file(raw_csv),
            "executeRequested": args.execute,
            "entries": entries,
        }
        if args.ledger:
            args.ledger.parent.mkdir(parents=True, exist_ok=True)
            args.ledger.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"ok": True, **ledger}, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"acquire_arkitscenes_confidence: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
