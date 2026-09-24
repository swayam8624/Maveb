#!/usr/bin/env python3
"""Build a bounded development prepared-world set from fresh and historical worlds."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ready_records(payload: dict[str, Any], source: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for record in payload.get("records", []):
        if record.get("status") != "ready":
            continue
        value = record.get("world")
        if not value:
            continue
        world = Path(str(value)).expanduser()
        if not world.is_absolute():
            world = source.parent / world
        if not world.is_file():
            continue
        copied = dict(record)
        copied["world"] = str(world.resolve())
        records.append(copied)
    return records


def append_unique(
    output: list[dict[str, Any]],
    seen_worlds: set[str],
    seen_scene_keys: set[tuple[str, str]],
    record: dict[str, Any],
) -> bool:
    world = str(record["world"])
    key = (str(record.get("datasetId", "")), str(record.get("sceneId", "")))
    if world in seen_worlds or (all(key) and key in seen_scene_keys):
        return False
    seen_worlds.add(world)
    if all(key):
        seen_scene_keys.add(key)
    output.append(record)
    return True


def build_bounded_set(
    *,
    base_payload: dict[str, Any] | None,
    base_source: Path | None,
    candidates: list[tuple[dict[str, Any], Path]],
    target_worlds: int,
    minimum_worlds: int = 2,
) -> tuple[dict[str, Any], list[str]]:
    if target_worlds < minimum_worlds:
        raise ValueError("target_worlds must be >= minimum_worlds")

    output: list[dict[str, Any]] = []
    seen_worlds: set[str] = set()
    seen_scene_keys: set[tuple[str, str]] = set()

    if base_payload is not None and base_source is not None:
        for record in ready_records(base_payload, base_source):
            append_unique(output, seen_worlds, seen_scene_keys, record)

    initial_count = len(output)
    existing_datasets = {
        str(record.get("datasetId"))
        for record in output
        if record.get("datasetId")
    }

    pool: list[dict[str, Any]] = []
    pool_seen_worlds = set(seen_worlds)
    pool_seen_scene_keys = set(seen_scene_keys)
    for payload, source in candidates:
        for record in ready_records(payload, source):
            world = str(record["world"])
            key = (str(record.get("datasetId", "")), str(record.get("sceneId", "")))
            if world in pool_seen_worlds or (all(key) and key in pool_seen_scene_keys):
                continue
            pool_seen_worlds.add(world)
            if all(key):
                pool_seen_scene_keys.add(key)
            copied = dict(record)
            copied["reuseSourceManifest"] = str(source.resolve())
            pool.append(copied)

    def consume(prefer_new_dataset: bool) -> None:
        nonlocal existing_datasets
        for record in pool:
            if len(output) >= target_worlds:
                return
            dataset_id = str(record.get("datasetId", ""))
            if prefer_new_dataset and (not dataset_id or dataset_id in existing_datasets):
                continue
            if append_unique(output, seen_worlds, seen_scene_keys, record):
                if dataset_id:
                    existing_datasets.add(dataset_id)

    consume(True)
    consume(False)

    if len(output) < minimum_worlds:
        raise ValueError(
            f"only {len(output)} valid prepared world(s) available; need at least {minimum_worlds}"
        )

    datasets = sorted(
        {
            str(record.get("datasetId"))
            for record in output
            if record.get("datasetId")
        }
    )
    result = {
        "schemaVersion": 1,
        "artifact": "maveb-cbrc-broad-prepared-worlds-development-bounded",
        "developmentOnly": True,
        "targetWorlds": target_worlds,
        "freshReadyWorlds": initial_count,
        "reusedHistoricalWorlds": max(0, len(output) - initial_count),
        "records": output,
        "readyWorlds": len(output),
        "blockedWorlds": 0,
        "failedWorlds": 0,
        "nativePreparedWorlds": sum(
            record.get("preparationPath") == "dataset-native-geometry"
            for record in output
        ),
        "rgbFallbackWorlds": sum(
            record.get("preparationPath") == "rgb-colmap-fallback"
            for record in output
        ),
        "datasets": datasets,
    }
    if base_source is not None:
        result["basePreparedWorldManifest"] = str(base_source.resolve())
    return result, datasets


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--base", type=Path)
    result.add_argument("--candidate", type=Path, action="append", default=[])
    result.add_argument("--target-worlds", type=int, default=4)
    result.add_argument("--minimum-worlds", type=int, default=2)
    result.add_argument("--output", type=Path, required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    base_payload = None
    base_source = None
    if args.base:
        base_source = args.base.expanduser().resolve()
        if base_source.is_file():
            base_payload = load(base_source)

    candidates: list[tuple[dict[str, Any], Path]] = []
    for candidate in args.candidate:
        path = candidate.expanduser().resolve()
        if not path.is_file():
            continue
        try:
            candidates.append((load(path), path))
        except (OSError, ValueError, json.JSONDecodeError):
            continue

    try:
        payload, datasets = build_bounded_set(
            base_payload=base_payload,
            base_source=base_source,
            candidates=candidates,
            target_worlds=args.target_worlds,
            minimum_worlds=args.minimum_worlds,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Prepared-world augmentation failed: {exc}", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(",".join(datasets))
    print(
        f"  ✓ bounded development world set: {payload['readyWorlds']} world(s) "
        f"({payload['freshReadyWorlds']} fresh, {payload['reusedHistoricalWorlds']} reused)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
