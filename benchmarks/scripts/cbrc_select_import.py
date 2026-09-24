#!/usr/bin/env python3
"""Select the effective dataset import for strict publication or fast development runs."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def development_candidate_fingerprints() -> list[dict[str, Any]]:
    enabled = os.environ.get("MAVEB_BROAD_REUSE_PREPARED_WORLDS", "0").lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return []
    raw = os.environ.get("MAVEB_BROAD_PREPARED_WORLD_CANDIDATES", "")
    fingerprints: list[dict[str, Any]] = []
    for value in raw.split(os.pathsep):
        if not value:
            continue
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            continue
        fingerprints.append(
            {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    return fingerprints


def describe(item: dict[str, Any]) -> str:
    name = str(item.get("datasetId", "unknown"))
    status = str(item.get("status", "unknown"))
    issues = [str(value) for value in item.get("issues", []) if str(value)]
    blocked_scenes = [
        str(scene.get("pairId") or scene.get("sceneId") or "unknown")
        for scene in item.get("scenes", [])
        if scene.get("status") != "ready"
    ]
    details = issues[:2]
    if blocked_scenes:
        details.append("blocked scenes: " + ", ".join(blocked_scenes[:4]))
    suffix = "; ".join(details) if details else "no ready scene set"
    return f"  - {name}: {status} — {suffix}"


def select_import(
    payload: dict[str, Any],
    *,
    allow_partial: bool,
    source: Path,
) -> tuple[dict[str, Any], list[str]]:
    datasets = list(payload.get("datasets", []))
    non_ready = [item for item in datasets if item.get("status") != "ready"]

    if non_ready and not allow_partial:
        print("", file=sys.stderr)
        print("Selected publication dataset set is not fully ready:", file=sys.stderr)
        for item in non_ready:
            print(describe(item), file=sys.stderr)
        print("", file=sys.stderr)
        print(
            "Full broad evidence is fail-closed. Fix the dataset roots/assets above, "
            "or run bash run_broad_benchmark_fast.sh for a development-only ready subset.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    if not allow_partial:
        selected = [str(item["datasetId"]) for item in datasets]
        print(
            f"  ✓ publication dataset gate: {len(selected)} selected dataset(s) fully ready",
            file=sys.stderr,
        )
        return payload, selected

    effective: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in datasets:
        ready_scenes = [
            scene for scene in item.get("scenes", []) if scene.get("status") == "ready"
        ]
        if not ready_scenes:
            skipped.append(item)
            continue
        filtered = copy.deepcopy(item)
        filtered["scenes"] = ready_scenes
        filtered["status"] = "ready"
        filtered["readyScenes"] = len(ready_scenes)
        filtered["expectedScenes"] = len(ready_scenes)
        effective.append(filtered)

    if not effective:
        print(
            "No ready dataset scenes are available for the fast development campaign.",
            file=sys.stderr,
        )
        for item in datasets:
            print(describe(item), file=sys.stderr)
        raise SystemExit(2)

    filtered_payload = copy.deepcopy(payload)
    filtered_payload["artifact"] = "maveb-cbrc-broad-benchmark-import-development-subset"
    filtered_payload["developmentOnly"] = True
    filtered_payload["sourceImport"] = str(source.resolve())
    filtered_payload["datasets"] = effective
    filtered_payload["readyDatasets"] = len(effective)
    filtered_payload["partialDatasets"] = 0
    filtered_payload["blockedDatasets"] = 0
    filtered_payload["developmentPreparedWorldCandidates"] = (
        development_candidate_fingerprints()
    )
    filtered_payload["developmentPreparedWorldTarget"] = int(
        os.environ.get("MAVEB_BROAD_FAST_WORLD_TARGET", "4")
    )

    selected = [str(item["datasetId"]) for item in effective]
    print(
        f"  ✓ development subset: {len(effective)} dataset(s), "
        f"{sum(len(item.get('scenes', [])) for item in effective)} ready scene(s)",
        file=sys.stderr,
    )
    if skipped:
        print(
            "  ↳ skipped datasets with no ready scenes: "
            + ", ".join(str(item.get("datasetId", "unknown")) for item in skipped),
            file=sys.stderr,
        )
    return filtered_payload, selected


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--input", type=Path, required=True)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--allow-partial", action="store_true")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    source = args.input.resolve()
    payload = load(source)
    effective, selected = select_import(
        payload,
        allow_partial=args.allow_partial,
        source=source,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(effective, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(",".join(selected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
