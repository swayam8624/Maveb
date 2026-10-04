#!/usr/bin/env python3
"""Cheap falsification probe for Criticality-Bounded Revision Cones.

This is deliberately representation-agnostic. It validates only the mathematical machinery:
tolerance-normalized non-negative gain propagation, contraction factor, tail certificate,
correlation length, and free-energy shell slope.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Case:
    branching: int
    edge_gain: float
    source_mass: float
    epsilon: float
    maximum_radius: int


def homogeneous_case(case: Case) -> dict:
    if case.branching < 0:
        raise ValueError("branching must be non-negative")
    if not (0.0 <= case.edge_gain < float("inf")):
        raise ValueError("edge gain must be finite and non-negative")
    if not (case.source_mass > 0.0 and math.isfinite(case.source_mass)):
        raise ValueError("source mass must be positive and finite")
    if not (case.epsilon > 0.0 and math.isfinite(case.epsilon)):
        raise ValueError("epsilon must be positive and finite")
    if case.maximum_radius < 0:
        raise ValueError("maximum radius must be non-negative")

    kappa = case.branching * case.edge_gain
    shell_mass = []
    free_energy = []
    for radius in range(case.maximum_radius + 1):
        mass = case.source_mass * (kappa ** radius)
        shell_mass.append(mass)
        free_energy.append(math.inf if mass == 0.0 else -math.log(mass))

    correlation_length = None
    certified_radius = None
    if 0.0 < kappa < 1.0:
        correlation_length = -1.0 / math.log(kappa)
        for radius in range(case.maximum_radius + 1):
            tail = case.source_mass * (kappa ** (radius + 1)) / (1.0 - kappa)
            if tail <= case.epsilon:
                certified_radius = radius
                break
    elif kappa == 0.0:
        correlation_length = 0.0
        certified_radius = 0

    slopes = []
    for left, right in zip(free_energy, free_energy[1:]):
        if math.isfinite(left) and math.isfinite(right):
            slopes.append(right - left)

    return {
        "branching": case.branching,
        "edgeGain": case.edge_gain,
        "kappa": kappa,
        "classification": (
            "subcritical" if kappa < 1.0 else "critical" if kappa == 1.0 else "supercritical"
        ),
        "sourceMass": case.source_mass,
        "epsilon": case.epsilon,
        "correlationLength": correlation_length,
        "certifiedRadius": certified_radius,
        "shellMass": shell_mass,
        "freeEnergy": free_energy,
        "freeEnergySlopes": slopes,
    }


def self_test() -> None:
    sub = homogeneous_case(Case(2, 0.2, 1.0, 1.0e-3, 32))
    assert sub["classification"] == "subcritical"
    assert abs(sub["kappa"] - 0.4) < 1.0e-12
    assert sub["certifiedRadius"] is not None
    assert all(s > 0.0 for s in sub["freeEnergySlopes"])

    critical = homogeneous_case(Case(4, 0.25, 1.0, 1.0e-3, 8))
    assert critical["classification"] == "critical"
    assert critical["certifiedRadius"] is None
    assert all(abs(s) < 1.0e-12 for s in critical["freeEnergySlopes"])

    sup = homogeneous_case(Case(3, 0.5, 1.0, 1.0e-3, 8))
    assert sup["classification"] == "supercritical"
    assert sup["certifiedRadius"] is None
    assert all(s < 0.0 for s in sup["freeEnergySlopes"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--branching", type=int, default=3)
    parser.add_argument("--edge-gain", type=float, default=0.2)
    parser.add_argument("--source-mass", type=float, default=1.0)
    parser.add_argument("--epsilon", type=float, default=1.0e-3)
    parser.add_argument("--maximum-radius", type=int, default=32)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()

    result = homogeneous_case(
        Case(
            branching=args.branching,
            edge_gain=args.edge_gain,
            source_mass=args.source_mass,
            epsilon=args.epsilon,
            maximum_radius=args.maximum_radius,
        )
    )
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
