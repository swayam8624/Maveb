#!/usr/bin/env python3
"""Falsification probe for a render-locality certificate under alpha compositing.

For a fixed set of unchanged layers U and an edited subset E, define the
edited opacity mass at one pixel as

    A(E) = 1 - product_i (1 - alpha_i).

For colors/background bounded to [0, 1], inserting E into U changes the
composited pixel by at most A(E) in L-infinity. Therefore two edited states
E_old and E_new satisfy

    ||R(U + E_old) - R(U + E_new)||_inf
        <= min(1, A(E_old) + A(E_new)).

This script attacks the bound with randomized interleavings, depth reordering,
colors, backgrounds, and edited-set cardinalities. It is a numerical
falsification test, not a proof; the accompanying theory note gives the
telescoping compositing argument.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

import numpy as np


def render(layers: list[tuple[float, np.ndarray]], background: np.ndarray) -> np.ndarray:
    transmittance = 1.0
    color = np.zeros(3, dtype=np.float64)
    for alpha, rgb in layers:
        alpha = float(np.clip(alpha, 0.0, 1.0))
        color += transmittance * alpha * rgb
        transmittance *= 1.0 - alpha
    return color + transmittance * background


def opacity_mass(alphas: list[float]) -> float:
    remaining = 1.0
    for alpha in alphas:
        remaining *= 1.0 - float(np.clip(alpha, 0.0, 1.0))
    return 1.0 - remaining


def run(seed: int, trials: int) -> dict:
    rng = np.random.default_rng(seed)
    violations = 0
    ratios: list[float] = []
    actuals: list[float] = []
    bounds: list[float] = []

    for _ in range(trials):
        unchanged_count = int(rng.integers(0, 20))
        old_count = int(rng.integers(1, 8))
        new_count = int(rng.integers(1, 8))
        background = rng.random(3)

        unchanged = [
            ("u", float(rng.beta(1.3, 5.0)), rng.random(3), float(rng.normal()))
            for _ in range(unchanged_count)
        ]

        # Log-uniform scale emphasizes the small-tail regime that a useful
        # locality certificate should accept, while still including large alpha.
        scale = 10.0 ** float(rng.uniform(-4.0, -0.2))
        old = [
            (
                "e",
                float(min(0.999, rng.beta(1.2, 3.0) * scale)),
                rng.random(3),
                float(rng.normal()),
            )
            for _ in range(old_count)
        ]
        new = [
            (
                "e",
                float(min(0.999, rng.beta(1.2, 3.0) * scale)),
                rng.random(3),
                float(rng.normal()),
            )
            for _ in range(new_count)
        ]

        old_layers = sorted(unchanged + old, key=lambda item: item[3])
        new_layers = sorted(unchanged + new, key=lambda item: item[3])
        old_color = render([(a, c) for _, a, c, _ in old_layers], background)
        new_color = render([(a, c) for _, a, c, _ in new_layers], background)

        actual = float(np.max(np.abs(old_color - new_color)))
        old_mass = opacity_mass([item[1] for item in old])
        new_mass = opacity_mass([item[1] for item in new])
        bound = min(1.0, old_mass + new_mass)

        if actual > bound + 1.0e-12:
            violations += 1
        ratio = actual / (bound + 1.0e-15)
        actuals.append(actual)
        bounds.append(bound)
        ratios.append(ratio)

    actual = np.asarray(actuals)
    bound = np.asarray(bounds)
    ratio = np.asarray(ratios)

    threshold_rows = {}
    for threshold in (1.0e-4, 1.0e-3, 1.0e-2, 5.0e-2, 1.0e-1):
        mask = bound <= threshold
        threshold_rows[str(threshold)] = {
            "count": int(mask.sum()),
            "maximum_actual_error": float(actual[mask].max()) if mask.any() else None,
            "median_tightness_ratio": float(np.median(ratio[mask])) if mask.any() else None,
            "p95_tightness_ratio": float(np.quantile(ratio[mask], 0.95)) if mask.any() else None,
        }

    return {
        "schemaVersion": 1,
        "experiment": "alpha-locality-certificate-v0",
        "environment": {
            "python": sys.version,
            "numpy": np.__version__,
            "platform": platform.platform(),
        },
        "configuration": {"seed": seed, "trials": trials},
        "violations": violations,
        "summary": {
            "actual_error_median": float(np.median(actual)),
            "actual_error_p95": float(np.quantile(actual, 0.95)),
            "bound_median": float(np.median(bound)),
            "bound_p95": float(np.quantile(bound, 0.95)),
            "tightness_ratio_median": float(np.median(ratio)),
            "tightness_ratio_p95": float(np.quantile(ratio, 0.95)),
            "tightness_ratio_max": float(ratio.max()),
            "thresholds": threshold_rows,
        },
        "decision": (
            "SURVIVES CHEAP FALSIFICATION: no randomized compositing violation. "
            "Next attack must use MAVEB's exact projected-Gaussian alpha path and real edit masks."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--trials", type=int, default=100_000)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("research/results/probes/alpha-locality-certificate-v0.json"),
    )
    args = parser.parse_args()
    result = run(args.seed, args.trials)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 1 if result["violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
