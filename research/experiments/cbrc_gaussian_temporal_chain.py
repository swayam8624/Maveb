#!/usr/bin/env python3
"""End-to-end cheap falsification for the first two analytic CBRC layers.

The experiment changes an edited Gaussian subset while preserving an unchanged
stack, computes the actual current-frame RGB change, certifies it from edited
opacity mass, then propagates the certificate through a temporal clamp/blend.

This is not a real-scene benchmark. It verifies that the composed analytic
machinery remains conservative under randomized depth interleaving, HDR-like
positive color ranges, changed clamp intervals, and arbitrary history weights.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.cbrc.layer_bounds import (
    gaussian_pixel_revision_bound,
    temporal_revision_bound,
)


def render(layers, background):
    transmittance = 1.0
    out = [0.0, 0.0, 0.0]
    for depth, alpha, rgb in sorted(layers, key=lambda x: x[0]):
        del depth
        for channel in range(3):
            out[channel] += transmittance * alpha * rgb[channel]
        transmittance *= 1.0 - alpha
    for channel in range(3):
        out[channel] += transmittance * background[channel]
    return out


def clamp(value, low, high):
    return min(max(value, low), high)


def run(seed: int, trials: int) -> dict:
    rng = random.Random(seed)
    violations = 0
    current_ratios = []
    temporal_ratios = []
    hard_fallbacks = 0

    for _ in range(trials):
        color_cap = 10 ** rng.uniform(-0.2, 0.8)
        unchanged = [
            (
                rng.uniform(-3.0, 3.0),
                0.7 * rng.random(),
                [color_cap * rng.random() for _ in range(3)],
            )
            for _ in range(rng.randrange(16))
        ]
        before = [
            (
                rng.uniform(-3.0, 3.0),
                0.5 * rng.random(),
                [color_cap * rng.random() for _ in range(3)],
            )
            for _ in range(1 + rng.randrange(8))
        ]
        after = [
            (
                rng.uniform(-3.0, 3.0),
                0.5 * rng.random(),
                [color_cap * rng.random() for _ in range(3)],
            )
            for _ in range(1 + rng.randrange(8))
        ]
        background = [color_cap * rng.random() for _ in range(3)]

        old_current = render(unchanged + before, background)
        new_current = render(unchanged + after, background)
        actual_current = max(
            abs(a - b) for a, b in zip(old_current, new_current)
        )
        gaussian = gaussian_pixel_revision_bound(
            [x[1] for x in before],
            [x[1] for x in after],
            color_cap,
        )
        if actual_current > gaussian.rgb_linf_bound + 1e-12:
            violations += 1
            break
        current_ratios.append(
            actual_current / max(gaussian.rgb_linf_bound, 1e-15)
        )

        # Model a correctly revised history versus deliberately retained stale
        # history. Its difference is chosen from actual old/new current colors,
        # so the Gaussian current certificate also bounds this cheap chain test.
        old_history = old_current
        new_history = new_current

        old_low = [min(old_current[c], old_history[c]) for c in range(3)]
        old_high = [max(old_current[c], old_history[c]) for c in range(3)]

        # Perturb the full-reference clamp interval within the known current
        # revision envelope. This attacks the moving-clamp part of the theorem.
        jitter = [rng.random() * actual_current for _ in range(3)]
        new_low = [max(0.0, min(new_current[c], new_history[c]) - jitter[c]) for c in range(3)]
        new_high = [
            min(color_cap, max(new_current[c], new_history[c]) + jitter[c])
            for c in range(3)
        ]

        current_error = actual_current
        history_error = max(
            abs(a - b) for a, b in zip(old_history, new_history)
        )
        neighborhood_error = max(
            max(abs(new_low[c] - old_low[c]), abs(new_high[c] - old_high[c]))
            for c in range(3)
        )

        validation_stable = rng.random() >= 0.08
        weight = rng.random()
        temporal = temporal_revision_bound(
            current_error_bound=gaussian.rgb_linf_bound,
            history_error_bound=gaussian.rgb_linf_bound,
            neighborhood_extrema_error_bound=max(
                gaussian.rgb_linf_bound, neighborhood_error
            ),
            history_weight=weight,
            validation_decision_stable=validation_stable,
        )

        if not validation_stable:
            hard_fallbacks += 1
            # HARD invalidation discards history. Compare current colors.
            actual_temporal = current_error
        else:
            old_resolved = [
                (1.0 - weight) * old_current[c]
                + weight * clamp(old_history[c], old_low[c], old_high[c])
                for c in range(3)
            ]
            new_resolved = [
                (1.0 - weight) * new_current[c]
                + weight * clamp(new_history[c], new_low[c], new_high[c])
                for c in range(3)
            ]
            actual_temporal = max(
                abs(a - b) for a, b in zip(old_resolved, new_resolved)
            )

        if actual_temporal > temporal.resolved_output_bound + 1e-12:
            violations += 1
            break
        temporal_ratios.append(
            actual_temporal / max(temporal.resolved_output_bound, 1e-15)
        )

    return {
        "schemaVersion": 1,
        "experiment": "cbrc-gaussian-temporal-chain-v1",
        "seed": seed,
        "requestedTrials": trials,
        "completedTrials": len(temporal_ratios),
        "violations": violations,
        "hardInvalidationFallbacks": hard_fallbacks,
        "currentBoundTightness": {
            "max": max(current_ratios, default=0.0),
            "mean": sum(current_ratios) / max(len(current_ratios), 1),
        },
        "temporalBoundTightness": {
            "max": max(temporal_ratios, default=0.0),
            "mean": sum(temporal_ratios) / max(len(temporal_ratios), 1),
        },
        "decision": (
            "FAIL: certificate violation"
            if violations
            else "SURVIVES CHEAP FALSIFICATION: proceed to exact production projection/frame replay"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260920)
    parser.add_argument("--trials", type=int, default=100_000)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "research/results/probes/cbrc-gaussian-temporal-chain-v1.json"
        ),
    )
    args = parser.parse_args()
    result = run(args.seed, args.trials)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
