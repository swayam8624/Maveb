#!/usr/bin/env python3
"""Fetch the exact frozen 3RScan subset used by MAVEB's broad benchmark.

This helper follows the official 3RScan public layout and requires the caller to explicitly
confirm acceptance of the 3RScan terms. It downloads only the 40 validation reference/rescan
pairs selected by the same deterministic rule used by cbrc_broad_benchmark.py, rather than
pulling the full ~94 GB release.

Official citation:
Wald et al., RIO: 3D Object Instance Re-Localization in Changing Indoor Environments, ICCV 2019.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

BASE_URL = "http://campar.in.tum.de/public_datasets/3RScan"
DATA_URL = BASE_URL + "/Dataset"
METADATA_URL = BASE_URL + "/3RScan.json"
TERMS_URL = BASE_URL + "/3RScanTOU.pdf"
FILES = (
    "mesh.refined.v2.obj",
    "semseg.v2.json",
    "labels.instances.annotated.v2.ply",
    "sequence.zip",
)


def run_curl(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    curl = shutil.which("curl")
    if not curl:
        raise RuntimeError("curl is required")
    cmd = [
        curl,
        "-L",
        "--fail",
        "--retry",
        "5",
        "--retry-delay",
        "2",
        "--continue-at",
        "-",
        "-o",
        str(target),
        url,
    ]
    subprocess.run(cmd, check=True)


def load_metadata(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("3RScan.json must contain a list")
    return payload


def changed_pairs(metadata: list[dict[str, Any]], target_pairs: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for scene in metadata:
        split = str(scene.get("type", "")).lower()
        if "val" not in split and "validation" not in split:
            continue
        reference = str(scene.get("reference", ""))
        if not reference:
            continue
        for rescan in scene.get("scans", []) or []:
            rescan_id = str(rescan.get("reference", ""))
            if not rescan_id:
                continue
            rigid = list(rescan.get("rigid", []) or [])
            removed = list(rescan.get("removed", []) or [])
            nonrigid = list(rescan.get("nonrigid", []) or [])
            change_count = len(rigid) + len(removed) + len(nonrigid)
            if change_count < 1:
                continue
            candidates.append(
                {
                    "pairId": f"{reference}__{rescan_id}",
                    "reference": reference,
                    "rescan": rescan_id,
                    "changeCount": change_count,
                    "rigidChanges": len(rigid),
                    "removedChanges": len(removed),
                    "nonrigidChanges": len(nonrigid),
                    "split": split,
                }
            )
    candidates.sort(key=lambda item: (-item["changeCount"], item["pairId"]))
    return candidates[:target_pairs]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=40)
    parser.add_argument("--accept-terms", action="store_true")
    args = parser.parse_args()

    if not args.accept_terms:
        print("3RScan terms:", TERMS_URL, file=sys.stderr)
        print("Re-run with --accept-terms only after you have accepted the 3RScan terms.", file=sys.stderr)
        return 2
    if args.pairs <= 0:
        parser.error("--pairs must be > 0")

    root = args.output_dir.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    metadata_path = root / "3RScan.json"
    if not metadata_path.is_file():
        print(f"Downloading metadata -> {metadata_path}")
        run_curl(METADATA_URL, metadata_path)

    metadata = load_metadata(metadata_path)
    pairs = changed_pairs(metadata, args.pairs)
    if len(pairs) < args.pairs:
        raise SystemExit(f"Only {len(pairs)} changed validation pairs found; expected {args.pairs}")

    scans = sorted({item["reference"] for item in pairs} | {item["rescan"] for item in pairs})
    freeze = {
        "schemaVersion": 1,
        "artifact": "maveb-3rscan-frozen-subset",
        "pairs": pairs,
        "pairCount": len(pairs),
        "scanCount": len(scans),
        "filesPerScan": list(FILES),
        "termsUrl": TERMS_URL,
        "metadataUrl": METADATA_URL,
        "citation": {
            "key": "wald2019",
            "title": "RIO: 3D Object Instance Re-Localization in Changing Indoor Environments",
            "venue": "ICCV",
            "year": 2019,
        },
    }
    write_json(root / "MAVEB_3RSCAN_SUBSET.json", freeze)

    total = len(scans) * len(FILES)
    current = 0
    for scan_id in scans:
        for filename in FILES:
            current += 1
            target = root / scan_id / filename
            if target.is_file() and target.stat().st_size > 0:
                print(f"[{current}/{total}] exists {scan_id}/{filename}")
                continue
            url = f"{DATA_URL}/{scan_id}/{filename}"
            print(f"[{current}/{total}] {scan_id}/{filename}")
            run_curl(url, target)

    print()
    print(f"3RScan MAVEB subset ready: {len(pairs)} pairs / {len(scans)} unique scans")
    print(root / "MAVEB_3RSCAN_SUBSET.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
