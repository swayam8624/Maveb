#!/usr/bin/env python3
"""Controlled synthetic benchmark for the CBRC reference certificate.

This tests certificate mechanics and local/global crossover. It is not evidence
for captured-world speedups. Results are emitted as JSONL for auditability.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.cbrc.core import QoI, certify_cone, greedy_minimum_work_cone


EDIT_TYPES = ("geometry", "appearance", "gaussian", "publication", "history")


def layered_graph(
    rng: np.random.Generator, layers: int, width: int, coupling: float
) -> np.ndarray:
    n = layers * width
    K = np.zeros((n, n), dtype=float)

    for layer in range(layers - 1):
        a0, a1 = layer * width, (layer + 1) * width
        b0, b1 = a1, (layer + 2) * width
        for u in range(a0, a1):
            mask = rng.random(width) < coupling
            gains = rng.uniform(0.01, 0.25, width) * mask
            K[b0:b1, u] = gains
    return K


def exact_dag_response(K: np.ndarray, source: np.ndarray) -> np.ndarray:
    """Finite Neumann response used as a synthetic analytical bound."""
    z = source.copy()
    frontier = source.copy()
    for _ in range(K.shape[0]):
        frontier = K @ frontier
        if np.max(np.abs(frontier)) < 1e-15:
            break
        z += frontier
    return z


def fixed_radius_cone(K: np.ndarray, seeds: set[int], radius: int) -> set[int]:
    C = set(seeds)
    frontier = set(seeds)
    for _ in range(radius):
        nxt = set()
        for u in frontier:
            for v in np.flatnonzero(K[:, u] > 0):
                if int(v) not in C:
                    nxt.add(int(v))
        C |= nxt
        frontier = nxt
        if not frontier:
            break
    return C


def trial(
    rng: np.random.Generator,
    *,
    layers: int,
    width: int,
    coupling: float,
    magnitude: float,
    epsilon: float,
    edit_type: str,
) -> dict:
    K = layered_graph(rng, layers, width, coupling)
    n = K.shape[0]
    source = np.zeros(n)

    changed = max(1, min(width, int(math.ceil(width * magnitude))))
    source_nodes = set(int(x) for x in rng.choice(width, size=changed, replace=False))
    source[list(source_nodes)] = 1.0
    z = exact_dag_response(K, source)

    work = rng.uniform(0.8, 1.2, n)
    qoi = QoI("state_linf", np.eye(n), epsilon)
    dependency_predecessors = [
        set(int(u) for u in np.flatnonzero(K[v, :] > 0.0))
        for v in range(n)
    ]

    cbrc = greedy_minimum_work_cone(
        K_cert=K,
        source=source,
        true_change_bound=z,
        hard_closure=source_nodes,
        dependency_predecessors=dependency_predecessors,
        work=work,
        qois=[qoi],
    )

    fixed = {}
    for radius in (0, 1, 2, 3):
        C = fixed_radius_cone(K, source_nodes, radius)
        cert = certify_cone(
            K_cert=K,
            source=source,
            true_change_bound=z,
            cone=C,
            dependency_predecessors=dependency_predecessors,
            work=work,
            qois=[qoi],
        )
        fixed[str(radius)] = {
            "work_ratio": cert.work / cert.full_work,
            "certified": cert.passes,
            "bound": cert.bound_by_qoi["state_linf"],
        }

    return {
        "layers": layers,
        "width": width,
        "nodes": n,
        "coupling": coupling,
        "magnitude": magnitude,
        "epsilon": epsilon,
        "edit_type": edit_type,
        "changed_fraction": len(source_nodes) / n,
        "cbrc": {
            "cone_fraction": len(cbrc.cone) / n,
            "work_ratio": cbrc.work / cbrc.full_work,
            "certified": cbrc.passes,
            "full_fallback": cbrc.used_full_rebuild,
            "bound": cbrc.bound_by_qoi["state_linf"],
            "susceptibility": cbrc.susceptibility,
            "transient_amplification": cbrc.transient_amplification,
        },
        "fixed_radius": fixed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260920)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument(
        "--pilot",
        action="store_true",
        help="Run a compact matrix instead of the frozen 750-cell matrix.",
    )
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    if args.pilot:
        sizes = [(4, 4), (6, 6)]
        edit_types = EDIT_TYPES[:2]
        magnitudes = (0.05, 0.20)
        couplings = (0.15, 0.45)
        epsilons = (0.05,)
    else:
        sizes = [(4, 4), (5, 6), (6, 8), (8, 10), (10, 12)]
        edit_types = EDIT_TYPES
        magnitudes = (0.02, 0.05, 0.10, 0.20, 0.40)
        couplings = (0.10, 0.30, 0.55)
        epsilons = (0.01, 0.05)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    trials = 0
    uncertified = 0
    fallbacks = 0

    with args.out.open("w", encoding="utf-8") as f:
        for layers, width in sizes:
            for edit_type in edit_types:
                for magnitude in magnitudes:
                    for coupling in couplings:
                        for epsilon in epsilons:
                            for rep in range(args.repeats):
                                row = trial(
                                    rng,
                                    layers=layers,
                                    width=width,
                                    coupling=coupling,
                                    magnitude=magnitude,
                                    epsilon=epsilon,
                                    edit_type=edit_type,
                                )
                                row["repeat"] = rep
                                f.write(json.dumps(row, sort_keys=True) + "\n")
                                trials += 1
                                uncertified += int(not row["cbrc"]["certified"])
                                fallbacks += int(row["cbrc"]["full_fallback"])

    print(
        json.dumps(
            {
                "trials": trials,
                "uncertified_outputs": uncertified,
                "full_fallbacks": fallbacks,
                "seed": args.seed,
                "pilot": args.pilot,
                "repeats": args.repeats,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
