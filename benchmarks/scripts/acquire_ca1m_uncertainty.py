#!/usr/bin/env python3
"""Acquire the frozen CA-1M captures for Maveb's metric-uncertainty study.

The script validates every selected video against Apple's CA-1M train/val index files in a local
`apple/ml-cubifyanything` clone, then downloads only the eight preregistered tar archives. It does
not inspect frame contents or metrics. Without --execute it emits a deterministic acquisition plan.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
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
        raise ValueError("CA-1M acquisition requires the frozen schema-v1 public split")
    if payload.get("source", {}).get("dataset") != "CA-1M / Cubify Anything":
        raise ValueError("public split is not a CA-1M evidence split")
    return payload, raw


def selected_scenes(payload: dict) -> list[str]:
    calibration = [str(v) for v in payload.get("calibrationScenes", [])]
    held_out = [str(v) for v in payload.get("heldOutScenes", [])]
    if len(calibration) < 3 or len(held_out) < 5:
        raise ValueError("frozen CA-1M split requires >=3 calibration and >=5 held-out scenes")
    if set(calibration) & set(held_out):
        raise ValueError("calibration/held-out scene leakage")
    return calibration + held_out


def load_url_index(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        url = line.strip()
        if not url:
            continue
        filename = url.rsplit("/", 1)[-1]
        stem = filename.removesuffix(".tar")
        parts = stem.split("-")
        if len(parts) < 3:
            raise ValueError(f"malformed CA-1M URL on line {number}: {url}")
        video_id = parts[-1]
        if not video_id.isdigit() or video_id in result:
            raise ValueError(f"invalid/duplicate CA-1M video ID in index: {video_id}")
        result[video_id] = url
    if not result:
        raise ValueError(f"empty CA-1M URL index: {path}")
    return result


def validate_split(payload: dict, train_urls: dict[str, str], val_urls: dict[str, str]) -> None:
    metadata = payload.get("sceneMetadata")
    if not isinstance(metadata, dict):
        raise ValueError("split is missing sceneMetadata")
    visits: dict[str, str] = {}
    for scene in selected_scenes(payload):
        entry = metadata.get(scene)
        if not isinstance(entry, dict):
            raise ValueError(f"missing metadata for {scene}")
        video_id = str(entry.get("videoId", ""))
        visit_id = str(entry.get("visitId", ""))
        ca1m_split = str(entry.get("ca1mSplit", ""))
        role = str(entry.get("role", ""))
        if scene != f"ca1m-{video_id}":
            raise ValueError(f"scene/video identity mismatch: {scene}")
        expected_role = "calibration" if scene in payload["calibrationScenes"] else "held-out"
        expected_ca1m = "train" if expected_role == "calibration" else "val"
        if role != expected_role or ca1m_split != expected_ca1m:
            raise ValueError(f"role/split mismatch for {scene}")
        index = train_urls if ca1m_split == "train" else val_urls
        if video_id not in index:
            raise ValueError(f"{scene} is absent from CA-1M {ca1m_split} index")
        previous = visits.get(visit_id)
        if not visit_id or previous is not None:
            raise ValueError(
                f"visit-level leakage: {previous or 'missing visit'} and {scene} share {visit_id}"
            )
        visits[visit_id] = scene


def plan(payload: dict, train_urls: dict[str, str], val_urls: dict[str, str], output: Path) -> list[dict]:
    entries = []
    for scene in selected_scenes(payload):
        metadata = payload["sceneMetadata"][scene]
        video_id = str(metadata["videoId"])
        split = str(metadata["ca1mSplit"])
        url = (train_urls if split == "train" else val_urls)[video_id]
        destination = output / f"ca1m-{split}-{video_id}.tar"
        entries.append(
            {
                "scene": scene,
                "role": metadata["role"],
                "videoId": video_id,
                "visitId": metadata["visitId"],
                "ca1mSplit": split,
                "url": url,
                "destination": str(destination.resolve()),
                "alreadyPresent": destination.is_file(),
            }
        )
    return entries


def download(entry: dict) -> None:
    destination = Path(entry["destination"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "curl",
        "--location",
        "--fail",
        "--retry",
        "3",
        "--continue-at",
        "-",
        "--output",
        str(destination),
        str(entry["url"]),
    ]
    subprocess.run(command, check=True)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--split",
        type=Path,
        default=repo_root / "benchmarks/experiments/metric-uncertainty-public-split-v1.json",
    )
    parser.add_argument("--ca1m-repo", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--ledger", type=Path)
    args = parser.parse_args()

    try:
        payload, split_bytes = load_split(args.split.resolve())
        ca1m_repo = args.ca1m_repo.resolve()
        train_index = ca1m_repo / "data/train.txt"
        val_index = ca1m_repo / "data/val.txt"
        if not train_index.is_file() or not val_index.is_file():
            raise ValueError("--ca1m-repo must contain data/train.txt and data/val.txt")
        train_urls = load_url_index(train_index)
        val_urls = load_url_index(val_index)
        validate_split(payload, train_urls, val_urls)
        output = args.output_dir.resolve()
        entries = plan(payload, train_urls, val_urls, output)

        if args.execute:
            for entry in entries:
                download(entry)
                destination = Path(entry["destination"])
                entry["downloaded"] = destination.is_file()
                entry["bytes"] = destination.stat().st_size if destination.is_file() else 0
            if not all(entry.get("downloaded") for entry in entries):
                raise ValueError("one or more selected CA-1M archives were not downloaded")

        ledger = {
            "schemaVersion": 1,
            "study": "metric-uncertainty-v1",
            "evidenceSource": "CA-1M FARO-registered GT depth",
            "splitId": payload["id"],
            "splitRevision": payload.get("revision"),
            "splitSha256": hashlib.sha256(split_bytes).hexdigest(),
            "trainIndexSha256": sha256_file(train_index),
            "valIndexSha256": sha256_file(val_index),
            "executeRequested": args.execute,
            "archives": entries,
        }
        if args.ledger:
            args.ledger.parent.mkdir(parents=True, exist_ok=True)
            args.ledger.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"ok": True, **ledger}, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"acquire_ca1m_uncertainty: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
