#!/usr/bin/env python3
"""Report and safely reclaim MAVEB benchmark storage."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import cbrc_storage


GIB = 1024 ** 3


def human(value: int) -> str:
    if value >= GIB:
        return f"{value / GIB:.2f} GiB"
    if value >= 1024 ** 2:
        return f"{value / 1024 ** 2:.1f} MiB"
    if value >= 1024:
        return f"{value / 1024:.1f} KiB"
    return f"{value} B"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def freeze_inputs_recoverable(freeze_dir: Path) -> tuple[bool, str]:
    freeze_files = [
        freeze_dir / "BROAD_CAMPAIGN_FREEZE.json",
        freeze_dir / "REVIEWER_STRESS_FREEZE.json",
    ]
    freeze_path = next((path for path in freeze_files if path.is_file()), None)
    if freeze_path is None:
        # A failed/incomplete freeze has no durable provenance and its inputs
        # are necessarily disposable because the freeze must be regenerated.
        return True, "incomplete freeze; inputs are disposable"

    try:
        payload = load(freeze_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False, f"cannot validate {freeze_path.name}"

    frozen = payload.get("frozen_inputs", [])
    if not isinstance(frozen, list) or not frozen:
        return False, "freeze provenance has no frozen_inputs"

    missing = []
    for item in frozen:
        if not isinstance(item, dict):
            continue
        source_value = item.get("source_archive")
        revision_value = item.get("source_revision")
        if not source_value or revision_value is None:
            missing.append(str(source_value or "<missing-source>"))
            if len(missing) >= 3:
                break
            continue
        source = Path(str(source_value))
        revision = int(revision_value)
        required = (
            source,
            Path(str(source) + f".gaussians.r{revision}.bin"),
            Path(str(source) + f".ownership.r{revision}.bin"),
        )
        for path in required:
            if not path.is_file():
                missing.append(str(path))
                break
        if len(missing) >= 3:
            break
    if missing:
        return False, "source prepared world or revision sidecars are missing"
    return True, "all case inputs can be rematerialized from prepared worlds"


def graphdeco_archive_candidate(data_root: Path) -> tuple[Path | None, bool]:
    archive = data_root / "graphdeco-pretrained/models.zip"
    models = data_root / "graphdeco-pretrained/models"
    if not archive.is_file():
        return None, False
    extracted = models.is_dir() and any(models.rglob("point_cloud.ply"))
    if not extracted:
        extracted = models.is_dir() and any(models.rglob("*.ply"))
    return archive, extracted


def report_path(label: str, path: Path) -> dict[str, Any]:
    physical = cbrc_storage.allocated_bytes(path)
    logical = cbrc_storage.logical_bytes(path)
    print(f"{label:<42} allocated={human(physical):>10} logical={human(logical):>10}")
    return {
        "label": label,
        "path": str(path),
        "allocatedBytes": physical,
        "logicalBytes": logical,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="MAVEB repository root",
    )
    parser.add_argument(
        "--data",
        type=Path,
        help="MAVEB dataset root; defaults to $MAVEB_DATA when set",
    )
    parser.add_argument(
        "--cleanup-safe",
        action="store_true",
        help=(
            "Delete only recoverable frozen case materializations and the "
            "GraphDECO zip when its extracted models are present."
        ),
    )
    parser.add_argument(
        "--minimum-free-gib",
        type=float,
        default=5.0,
        help="Exit non-zero when free disk is below this threshold after cleanup/report.",
    )
    args = parser.parse_args()

    repo = args.repo.expanduser().resolve()
    import os

    data_value = args.data or (
        Path(os.environ["MAVEB_DATA"]) if os.environ.get("MAVEB_DATA") else None
    )
    data = None if data_value is None else data_value.expanduser().resolve()

    print("MAVEB STORAGE DOCTOR")
    print("=" * 72)
    print(f"repo : {repo}")
    print(f"data : {data if data else 'not configured'}")
    print(f"free : {human(cbrc_storage.free_bytes(repo))}")
    print("note : allocated bytes may double-count shared APFS clone extents; free disk is authoritative")
    print()

    records: list[dict[str, Any]] = []
    for relative in (
        "build/broad-benchmark-smoke",
        "build/broad-benchmark-paper",
        "build/reviewer-stress",
        "build/ci",
    ):
        path = repo / relative
        if path.exists():
            records.append(report_path(relative, path))

    if data and data.exists():
        print()
        for name in (
            "graphdeco-pretrained",
            "3RScan",
            "ARKitScenes",
            "BonnRGBD",
        ):
            path = data / name
            if path.exists():
                records.append(report_path(f"datasets/{name}", path))

    if data and data.exists():
        archives: list[tuple[int, Path]] = []
        for pattern in ("*.zip", "*.tar", "*.tar.gz", "*.tgz", "*.7z"):
            for path in data.rglob(pattern):
                try:
                    if path.is_file():
                        archives.append((cbrc_storage.allocated_bytes(path), path))
                except OSError:
                    continue
        if archives:
            print()
            print("DATASET ARCHIVES (report only unless explicitly marked SAFE below)")
            print("-" * 72)
            seen: set[Path] = set()
            for size, path in sorted(archives, reverse=True):
                if path in seen:
                    continue
                seen.add(path)
                print(f"{human(size):>10}  {path}")

    candidates: list[tuple[str, Path, str]] = []
    print()
    print("SAFE CLEANUP CANDIDATES")
    print("-" * 72)

    for root in (
        repo / "build/broad-benchmark-smoke/frozen",
        repo / "build/broad-benchmark-paper/frozen",
        repo / "build/reviewer-stress/frozen",
    ):
        inputs = root / "inputs"
        if not inputs.exists():
            continue
        safe, reason = freeze_inputs_recoverable(root)
        size = cbrc_storage.allocated_bytes(inputs)
        state = "SAFE" if safe else "KEEP"
        print(f"{state:<5} {human(size):>10}  {inputs}  ({reason})")
        if safe:
            candidates.append(("frozen case inputs", inputs, reason))

    if data:
        archive, extracted = graphdeco_archive_candidate(data)
        if archive is not None:
            size = cbrc_storage.allocated_bytes(archive)
            state = "SAFE" if extracted else "KEEP"
            reason = (
                "extracted GraphDECO models are present"
                if extracted
                else "extracted models could not be verified"
            )
            print(f"{state:<5} {human(size):>10}  {archive}  ({reason})")
            if extracted:
                candidates.append(("GraphDECO download archive", archive, reason))

    reclaimed = 0
    if args.cleanup_safe:
        print()
        print("CLEANING SAFE CANDIDATES")
        print("-" * 72)
        for label, path, reason in candidates:
            before = cbrc_storage.allocated_bytes(path)
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
            reclaimed += before
            print(f"deleted {human(before):>10}  {label}: {path}")
        print(f"reclaimed: {human(reclaimed)}")

    free = cbrc_storage.free_bytes(repo)
    print()
    print(f"free now: {human(free)}")

    output = {
        "schemaVersion": 1,
        "artifact": "maveb-storage-doctor",
        "repo": str(repo),
        "data": None if data is None else str(data),
        "freeBytes": free,
        "reclaimedBytes": reclaimed,
        "records": records,
    }
    report = repo / "build/STORAGE_REPORT.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(f"report  : {report}")

    minimum = max(0.0, args.minimum_free_gib) * GIB
    return 0 if free >= minimum else 3


if __name__ == "__main__":
    raise SystemExit(main())
