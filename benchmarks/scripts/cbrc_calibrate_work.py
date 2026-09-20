#!/usr/bin/env python3
"""Freeze CBRC heterogeneous work coefficients from isolated microbenchmarks.

Each JSONL row measures one native work domain in isolation:
  {
    "domain": "gaussiansUpdated",
    "unit": "gaussians",
    "units": 10000,
    "elapsed_ms": 2.4,
    "baseline_ms": 0.1,
    "calibration_id": "m2pro-2026-09-20"
  }

The coefficient sample is max(0, elapsed_ms-baseline_ms)/units. Final
cost_per_unit is the median across repeats. This script does not fit on final
CBRC evaluation outcomes.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def finite(value: Any, name: str, *, positive: bool = False) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    if positive and number <= 0.0:
        raise ValueError(f"{name} must be positive")
    if not positive and number < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return number


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lo = int(math.floor(position))
    hi = int(math.ceil(position))
    if lo == hi:
        return ordered[lo]
    t = position - lo
    return ordered[lo] * (1.0 - t) + ordered[hi] * t


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]
    if not rows:
        raise ValueError("calibration input is empty")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("every calibration row must be an object")
    return rows


def calibrate(
    rows: list[dict[str, Any]],
    *,
    version: str,
    minimum_repeats: int = 5,
) -> dict[str, Any]:
    if not version.strip():
        raise ValueError("calibration version must be non-empty")
    if minimum_repeats < 1:
        raise ValueError("minimum_repeats must be positive")

    samples: dict[str, list[float]] = defaultdict(list)
    units: dict[str, str] = {}
    calibration_ids: set[str] = set()

    for index, row in enumerate(rows):
        domain = str(row.get("domain", "")).strip()
        unit = str(row.get("unit", "")).strip()
        if not domain or not unit:
            raise ValueError(f"row {index} requires domain and unit")
        native_units = finite(row.get("units"), f"row {index}.units", positive=True)
        elapsed = finite(row.get("elapsed_ms"), f"row {index}.elapsed_ms")
        baseline = finite(row.get("baseline_ms", 0.0), f"row {index}.baseline_ms")
        if baseline > elapsed:
            raise ValueError(f"row {index} baseline_ms exceeds elapsed_ms")

        previous_unit = units.setdefault(domain, unit)
        if previous_unit != unit:
            raise ValueError(
                f"domain {domain} changes native units: {previous_unit} vs {unit}"
            )

        coefficient = max(0.0, elapsed - baseline) / native_units
        samples[domain].append(coefficient)
        calibration_id = str(row.get("calibration_id", "")).strip()
        if calibration_id:
            calibration_ids.add(calibration_id)

    domains: dict[str, Any] = {}
    for domain, values in sorted(samples.items()):
        if len(values) < minimum_repeats:
            raise ValueError(
                f"domain {domain} has {len(values)} repeats; "
                f"requires at least {minimum_repeats}"
            )
        domains[domain] = {
            "unit": units[domain],
            "cost_per_unit": statistics.median(values),
            "calibration_samples": len(values),
            "sample_p25": percentile(values, 0.25),
            "sample_p75": percentile(values, 0.75),
            "sample_min": min(values),
            "sample_max": max(values),
        }

    return {
        "schemaVersion": 1,
        "version": version,
        "cost_unit": "ms",
        "calibration_ids": sorted(calibration_ids),
        "domains": domains,
        "freeze_rule": (
            "Coefficients are medians of isolated pre-evaluation microbenchmarks. "
            "Do not refit them on final CBRC experiment outcomes."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--minimum-repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = calibrate(
        load_rows(args.input),
        version=args.version,
        minimum_repeats=args.minimum_repeats,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(args.output.suffix + ".tmp")
    tmp.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    tmp.replace(args.output)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
