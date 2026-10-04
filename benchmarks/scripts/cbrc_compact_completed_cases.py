#!/usr/bin/env python3
"""Compact completed CBRC case evidence without breaking resume/audit.

A completed case is resumable from four canonical small artifacts:
  replay-manifest.json
  revision-row.json
  baselines.json
  CASE_COMPLETE.json

The final v5/v6 analyses only require those files. Heavy per-case render/capture
artifacts are reproducible from the frozen campaign and prepared worlds, so this
utility can reclaim them after CASE_COMPLETE exists.

Default mode is a dry run. --execute performs deletion. --watch repeatedly
compacts newly completed cases. --purge-incomplete removes partial case
directories, but should only be used while no campaign workers are running.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

KEEP_FILES = {
    "CASE_COMPLETE.json",
    "replay-manifest.json",
    "revision-row.json",
    "baselines.json",
    "provenance.json",
}

REQUIRED_FILES = {
    "CASE_COMPLETE.json",
    "replay-manifest.json",
    "revision-row.json",
    "baselines.json",
}


def path_size(path: Path) -> int:
    if not path.exists() and not path.is_symlink():
        return 0
    if path.is_symlink() or path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for root, _, files in os.walk(path, followlinks=False):
        for name in files:
            candidate = Path(root) / name
            try:
                total += candidate.stat().st_size
            except OSError:
                pass
    return total


def human(value: int) -> str:
    gib = 1024 ** 3
    mib = 1024 ** 2
    if value >= gib:
        return f"{value / gib:.2f} GiB"
    if value >= mib:
        return f"{value / mib:.1f} MiB"
    if value >= 1024:
        return f"{value / 1024:.1f} KiB"
    return f"{value} B"


def valid_json(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict)


def complete_case(case_dir: Path) -> bool:
    for name in REQUIRED_FILES:
        path = case_dir / name
        if not path.is_file() or not valid_json(path):
            return False
    marker = json.loads((case_dir / "CASE_COMPLETE.json").read_text(encoding="utf-8"))
    return bool(marker.get("caseId")) and bool(marker.get("executionSignature"))


def compact_case(case_dir: Path, *, execute: bool) -> tuple[int, int]:
    """Return (bytes_before, bytes_reclaimed)."""
    before = path_size(case_dir)
    if not complete_case(case_dir):
        return before, 0

    reclaimed = 0
    for child in list(case_dir.iterdir()):
        if child.name in KEEP_FILES:
            continue
        size = path_size(child)
        reclaimed += size
        if not execute:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=True)

    if execute:
        marker_path = case_dir / "CASE_COMPLETE.json"
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        marker["evidenceCompacted"] = True
        marker["compactionSchemaVersion"] = 1
        marker["reclaimedBytes"] = int(reclaimed)
        marker_path.write_text(
            json.dumps(marker, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return before, reclaimed


def compact_root(
    campaign_dir: Path,
    *,
    execute: bool,
    purge_incomplete: bool,
) -> dict[str, Any]:
    cases_root = campaign_dir / "cases"
    if not cases_root.is_dir():
        return {
            "casesSeen": 0,
            "completedCases": 0,
            "incompleteCases": 0,
            "reclaimedBytes": 0,
            "purgedIncompleteBytes": 0,
        }

    completed = 0
    incomplete = 0
    reclaimed = 0
    purged = 0
    seen = 0

    for case_dir in sorted(path for path in cases_root.iterdir() if path.is_dir()):
        seen += 1
        if complete_case(case_dir):
            completed += 1
            _, case_reclaimed = compact_case(case_dir, execute=execute)
            reclaimed += case_reclaimed
            continue

        incomplete += 1
        if purge_incomplete:
            size = path_size(case_dir)
            purged += size
            if execute:
                shutil.rmtree(case_dir)

    return {
        "casesSeen": seen,
        "completedCases": completed,
        "incompleteCases": incomplete,
        "reclaimedBytes": reclaimed,
        "purgedIncompleteBytes": purged,
    }


def free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def print_report(report: dict[str, Any], free: int) -> None:
    print(
        "completed={completedCases} incomplete={incompleteCases} "
        "reclaimable={reclaim} purgeable_partial={purge} free={free}".format(
            completedCases=report["completedCases"],
            incompleteCases=report["incompleteCases"],
            reclaim=human(int(report["reclaimedBytes"])),
            purge=human(int(report["purgedIncompleteBytes"])),
            free=human(free),
        ),
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--purge-incomplete", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=2.0)
    parser.add_argument(
        "--stop-file",
        type=Path,
        help="In watch mode, exit when this path exists.",
    )
    args = parser.parse_args()

    campaign_dir = args.campaign_dir.expanduser().resolve()
    if args.interval_seconds <= 0:
        raise SystemExit("--interval-seconds must be positive")

    if not args.watch:
        report = compact_root(
            campaign_dir,
            execute=args.execute,
            purge_incomplete=args.purge_incomplete,
        )
        print_report(report, free_bytes(campaign_dir.parent))
        return 0

    if args.purge_incomplete:
        raise SystemExit("--purge-incomplete is intentionally unavailable in --watch mode")

    stop_file = args.stop_file.expanduser().resolve() if args.stop_file else None
    last_completed = -1
    while True:
        if stop_file is not None and stop_file.exists():
            return 0
        report = compact_root(
            campaign_dir,
            execute=args.execute,
            purge_incomplete=False,
        )
        if int(report["completedCases"]) != last_completed:
            print_report(report, free_bytes(campaign_dir.parent))
            last_completed = int(report["completedCases"])
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
