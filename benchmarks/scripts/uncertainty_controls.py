#!/usr/bin/env python3
"""Create deterministic confidence controls for Maveb metric-uncertainty experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
from typing import Iterable


def parse_rows(lines: Iterable[str]) -> list[dict]:
    rows = []
    for line_number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
            confidence = float(row["sensorConfidence"])
            scene = str(row["scene"])
            sample_id = str(row.get("sampleId", f"line-{line_number}"))
            if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
                raise ValueError("sensorConfidence must be finite and in [0, 1]")
            if not scene or not sample_id:
                raise ValueError("scene and sampleId must be non-empty")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid control row on line {line_number}: {exc}") from exc
        row = dict(row)
        row["scene"] = scene
        row["sampleId"] = sample_id
        rows.append(row)
    if not rows:
        raise ValueError("confidence control input is empty")
    return rows


def _scene_seed(scene: str, seed: int) -> int:
    digest = hashlib.sha256(f"{seed}|{scene}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def shuffled_confidence(rows: list[dict], seed: int) -> list[dict]:
    """Permute confidence within each scene while preserving its exact empirical distribution."""

    groups: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        groups.setdefault(row["scene"], []).append(index)
    result = [dict(row) for row in rows]
    for scene in sorted(groups):
        indices = sorted(groups[scene], key=lambda index: rows[index]["sampleId"])
        values = [float(rows[index]["sensorConfidence"]) for index in indices]
        permutation = list(range(len(values)))
        random.Random(_scene_seed(scene, seed)).shuffle(permutation)
        if len(values) > 1 and all(source == target for target, source in enumerate(permutation)):
            permutation = permutation[1:] + permutation[:1]
        for target_index, source_index in zip(indices, permutation):
            result[target_index]["sensorConfidence"] = values[source_index]
            result[target_index]["confidenceControl"] = "shuffled-within-scene"
            result[target_index]["confidenceControlSeed"] = seed
    return result


def constant_confidence(rows: list[dict], value: float) -> list[dict]:
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("constant confidence must be finite and in [0, 1]")
    result = []
    for row in rows:
        controlled = dict(row)
        controlled["sensorConfidence"] = value
        controlled["confidenceControl"] = "constant"
        controlled["confidenceControlValue"] = value
        result.append(controlled)
    return result


def intact_confidence(rows: list[dict]) -> list[dict]:
    result = []
    for row in rows:
        controlled = dict(row)
        controlled["confidenceControl"] = "intact"
        result.append(controlled)
    return result


def apply_control(rows: list[dict], mode: str, *, seed: int, constant: float) -> list[dict]:
    if mode == "intact":
        return intact_confidence(rows)
    if mode == "constant":
        return constant_confidence(rows, constant)
    if mode == "shuffled":
        return shuffled_confidence(rows, seed)
    raise ValueError(f"unknown confidence control: {mode}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("intact", "constant", "shuffled"), required=True)
    parser.add_argument("--constant", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    try:
        input_bytes = args.input.read_bytes()
        rows = parse_rows(input_bytes.decode("utf-8").splitlines())
        controlled = apply_control(rows, args.mode, seed=args.seed, constant=args.constant)
    except (OSError, ValueError) as exc:
        print(f"uncertainty_controls: {exc}")
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as stream:
        for row in controlled:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    output_bytes = args.output.read_bytes()
    metadata = {
        "schemaVersion": 1,
        "mode": args.mode,
        "seed": args.seed,
        "constant": args.constant if args.mode == "constant" else None,
        "inputSha256": hashlib.sha256(input_bytes).hexdigest(),
        "outputSha256": hashlib.sha256(output_bytes).hexdigest(),
        "rows": len(controlled),
        "scenes": sorted({row["scene"] for row in controlled}),
    }
    args.output.with_suffix(args.output.suffix + ".meta.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({"ok": True, **metadata}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
