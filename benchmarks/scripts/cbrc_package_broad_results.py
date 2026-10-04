#!/usr/bin/env python3
"""Package broad MAVEB benchmark evidence for Git without dataset bytes/local paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

JSON_FILES = [
    "BROAD_CAMPAIGN_COMPLETE.json",
    "import/BROAD_IMPORT.json",
    "worlds/BROAD_WORLDS.json",
    "calibration/work-cost-model.json",
    "frozen/broad-campaign.json",
    "frozen/BROAD_CAMPAIGN_FREEZE.json",
    "campaign/campaign-gates.json",
    "campaign/campaign-evaluation.json",
    "campaign/planner-parity.json",
    "visual-quality/CBRC_VISUAL_QUALITY.json",
    "statistics/CROSS_DATASET_STATISTICS.json",
]
JSONL_FILES = [
    "campaign/campaign-rows.jsonl",
    "campaign/campaign-baselines.jsonl",
    "campaign/campaign-timings.jsonl",
]
PLAIN_FILES = [
    "visual-quality/CBRC_VISUAL_QUALITY.csv",
    "visual-quality/F13_benchmark_visual_quality.png",
    "statistics/dataset-summary.csv",
    "statistics/CROSS_DATASET_STATISTICS.md",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def safe_string(value: str) -> str:
    if value.startswith(("http://", "https://", "sha256:", "$")):
        return value
    try:
        path = Path(value)
        if path.is_absolute():
            return f"$LOCAL_PATH/{path.name}"
    except (OSError, ValueError):
        pass
    return value


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return safe_string(value)
    return value


def write_json(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = sanitize(json.loads(source.read_text(encoding="utf-8")))
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    output = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if line.strip():
            output.append(json.dumps(sanitize(json.loads(line)), sort_keys=True))
    target.write_text("\n".join(output) + ("\n" if output else ""), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    source_root = args.results_root.resolve()
    output_root = args.output_dir.resolve()
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)

    missing = []
    copied = []
    for relative in JSON_FILES:
        source = source_root / relative
        if not source.is_file():
            missing.append(relative)
            continue
        target = output_root / relative
        write_json(source, target)
        copied.append(target)

    for relative in JSONL_FILES:
        source = source_root / relative
        if not source.is_file():
            missing.append(relative)
            continue
        target = output_root / relative
        write_jsonl(source, target)
        copied.append(target)

    for relative in PLAIN_FILES:
        source = source_root / relative
        if not source.is_file():
            # The representative image is optional if rendering dependencies were unavailable.
            if relative.endswith(".png"):
                continue
            missing.append(relative)
            continue
        target = output_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(target)

    if missing:
        raise SystemExit("missing evidence files:\n" + "\n".join(missing))

    manifest = {
        "schemaVersion": 1,
        "artifact": "maveb-cbrc-broad-git-evidence-package",
        "sourceRootRedacted": True,
        "datasetBytesIncluded": False,
        "files": [
            {
                "path": str(path.relative_to(output_root)),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in sorted(copied)
        ],
    }
    manifest_path = output_root / "EVIDENCE_PACKAGE.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
