#!/usr/bin/env python3
"""Research metrics for MAVEB continual-world experiments.

The metrics stay decomposed by physical quantity. In particular, Update
Locality Ratio does not silently add bytes, primitive inspections, mesh patches,
or milliseconds together. An aggregate is emitted only when the experiment
provides explicit cost weights that put those counters on a common scale.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def _finite_nonnegative(value: float, name: str) -> float:
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return value


def update_locality_ratio(
    incremental: dict[str, float],
    full: dict[str, float],
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    keys = sorted(set(incremental) | set(full))
    if not keys:
        raise ValueError("work counters cannot be empty")

    components: dict[str, Any] = {}
    weighted_num = 0.0
    weighted_den = 0.0
    aggregate_enabled = weights is not None

    for key in keys:
        inc = _finite_nonnegative(incremental.get(key, 0.0), f"incremental.{key}")
        ref = _finite_nonnegative(full.get(key, 0.0), f"full.{key}")
        components[key] = {
            "incremental": inc,
            "full": ref,
            "ratio": None if ref == 0 else inc / ref,
        }
        if aggregate_enabled:
            weight = _finite_nonnegative(weights.get(key, 0.0), f"weight.{key}")
            weighted_num += weight * inc
            weighted_den += weight * ref

    return {
        "ratio": None
        if (not aggregate_enabled or weighted_den == 0)
        else weighted_num / weighted_den,
        "components": components,
        "weighted_incremental_work": None if not aggregate_enabled else weighted_num,
        "weighted_full_work": None if not aggregate_enabled else weighted_den,
        "aggregate_requires_explicit_cost_weights": True,
    }


def unchanged_world_damage(samples: list[dict[str, float]]) -> dict[str, Any]:
    if not samples:
        raise ValueError("unchanged-world samples cannot be empty")

    geometry: list[float] = []
    rendering: list[float] = []
    for index, sample in enumerate(samples):
        geometry.append(
            _finite_nonnegative(
                sample.get("geometry_displacement", 0.0),
                f"samples[{index}].geometry_displacement",
            )
        )
        rendering.append(
            _finite_nonnegative(
                sample.get("render_absolute_error", 0.0),
                f"samples[{index}].render_absolute_error",
            )
        )

    def stats(values: list[float]) -> dict[str, float]:
        ordered = sorted(values)
        count = len(ordered)
        p95 = ordered[min(count - 1, math.ceil(0.95 * count) - 1)]
        mean = sum(ordered) / count
        rmse = math.sqrt(sum(value * value for value in ordered) / count)
        return {"mean": mean, "rmse": rmse, "p95": p95, "max": ordered[-1]}

    return {
        "sample_count": len(samples),
        "geometry": stats(geometry),
        "render": stats(rendering),
    }


def representation_churn(before: dict[str, str], after: dict[str, str]) -> dict[str, Any]:
    ids = set(before) | set(after)
    births = deaths = switches = stable = 0
    for entity in ids:
        previous = before.get(entity)
        current = after.get(entity)
        if previous is None:
            births += 1
        elif current is None:
            deaths += 1
        elif current != previous:
            switches += 1
        else:
            stable += 1

    denominator = max(1, len(ids))
    return {
        "births": births,
        "deaths": deaths,
        "representation_switches": switches,
        "stable": stable,
        "churn_rate": (births + deaths + switches) / denominator,
    }


def identity_survival(expected: dict[str, str], observed: dict[str, str]) -> dict[str, Any]:
    if not expected:
        raise ValueError("expected identity mapping cannot be empty")

    correct = missing = switched = 0
    for token, target in expected.items():
        found = observed.get(token)
        if found is None:
            missing += 1
        elif found == target:
            correct += 1
        else:
            switched += 1

    total = len(expected)
    return {
        "total": total,
        "correct": correct,
        "missing": missing,
        "switched": switched,
        "survival_rate": correct / total,
        "switch_rate": switched / total,
        "missing_rate": missing / total,
    }


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {"schemaVersion": 1}
    if "work" in payload:
        work = payload["work"]
        output["updateLocalityRatio"] = update_locality_ratio(
            work["incremental"], work["full"], work.get("weights")
        )
    if "unchangedWorldSamples" in payload:
        output["unchangedWorldDamage"] = unchanged_world_damage(
            payload["unchangedWorldSamples"]
        )
    if "representations" in payload:
        rep = payload["representations"]
        output["representationChurn"] = representation_churn(
            rep["before"], rep["after"]
        )
    if "identities" in payload:
        identity = payload["identities"]
        output["identitySurvival"] = identity_survival(
            identity["expected"], identity["observed"]
        )
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = evaluate(json.loads(args.input.read_text(encoding="utf-8")))
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
