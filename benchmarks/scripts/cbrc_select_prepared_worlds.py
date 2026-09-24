#!/usr/bin/env python3
"""Select a reusable prepared-world manifest for a development campaign."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def select_ready_worlds(payload: dict[str, Any], source: Path) -> tuple[dict[str, Any], list[str]]:
    ready: list[dict[str, Any]] = []
    for record in payload.get("records", []):
        if record.get("status") != "ready":
            continue
        world_value = record.get("world")
        if not world_value:
            continue
        world = Path(str(world_value)).expanduser()
        if not world.is_file():
            continue
        copied = dict(record)
        copied["world"] = str(world.resolve())
        ready.append(copied)

    unique_worlds: set[str] = set()
    filtered: list[dict[str, Any]] = []
    for record in ready:
        world = str(record["world"])
        if world in unique_worlds:
            continue
        unique_worlds.add(world)
        filtered.append(record)

    if len(filtered) < 2:
        raise ValueError(f"{source}: fewer than two reusable prepared worlds")

    datasets = sorted(
        {
            str(record.get("datasetId"))
            for record in filtered
            if record.get("datasetId")
        }
    )
    result = {
        "schemaVersion": payload.get("schemaVersion", 1),
        "artifact": "maveb-cbrc-broad-prepared-worlds-development-reuse",
        "developmentOnly": True,
        "sourcePreparedWorldManifest": str(source.resolve()),
        "records": filtered,
        "readyWorlds": len(filtered),
        "blockedWorlds": 0,
        "failedWorlds": 0,
        "nativePreparedWorlds": sum(
            record.get("preparationPath") == "dataset-native-geometry"
            for record in filtered
        ),
        "rgbFallbackWorlds": sum(
            record.get("preparationPath") == "rgb-colmap-fallback"
            for record in filtered
        ),
        "datasets": datasets,
    }
    return result, datasets


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--candidate", type=Path, action="append", required=True)
    result.add_argument("--output", type=Path, required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    failures: list[str] = []
    for candidate in args.candidate:
        path = candidate.expanduser().resolve()
        if not path.is_file():
            failures.append(f"{path}: manifest missing")
            continue
        try:
            selected, datasets = select_ready_worlds(load(path), path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            failures.append(str(exc))
            continue
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(selected, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(",".join(datasets))
        print(
            f"  ✓ reused {selected['readyWorlds']} prepared world(s) from {path}",
            file=__import__("sys").stderr,
        )
        return 0

    print("No reusable prepared-world fallback was found:", file=__import__("sys").stderr)
    for failure in failures:
        print(f"  - {failure}", file=__import__("sys").stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
