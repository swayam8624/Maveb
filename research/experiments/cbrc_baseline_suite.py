#!/usr/bin/env python3
"""Run frozen CBRC baselines and ablations on one machine-readable graph.

The suite deliberately separates *selection strategy* from *certificate
validation*. Every selected cone is re-certified by the same conservative CBRC
certificate implementation. Unsafe baselines are retained with passes=false;
they are never silently discarded from comparison tables.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from research.cbrc.core import (
    Certificate,
    QoI,
    certify_cone,
    greedy_minimum_work_cone,
    predecessor_closure,
)
from research.cbrc.edges import (
    EdgeClass,
    RevisionEdge,
    certificate_transfer,
    empirical_priority,
    exact_predecessors,
    validate_edges,
)


def _node_index(payload: dict[str, Any]) -> dict[str, int]:
    nodes = payload.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("graph requires non-empty nodes")
    result: dict[str, int] = {}
    for index, node in enumerate(nodes):
        name = str(node.get("id", "")).strip()
        if not name or name in result:
            raise ValueError("node ids must be unique non-empty strings")
        result[name] = index
    return result


def _edges(payload: dict[str, Any], ids: dict[str, int]) -> list[RevisionEdge]:
    result: list[RevisionEdge] = []
    for raw in payload.get("edges", []):
        cls = EdgeClass(str(raw["class"]).lower())
        gain = raw.get("gain")
        result.append(
            RevisionEdge(
                src=ids[str(raw["source"])],
                dst=ids[str(raw["target"])],
                edge_class=cls,
                gain=None if gain is None else float(gain),
                bound_id=raw.get("bound_id"),
            )
        )
    return validate_edges(len(ids), result)


def _vectors(payload: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    nodes = payload["nodes"]
    work = np.asarray([float(n.get("work", 0.0)) for n in nodes], dtype=float)
    change = np.asarray(
        [float(n.get("true_change_bound", 0.0)) for n in nodes], dtype=float
    )
    source = np.asarray([float(n.get("source_bound", 0.0)) for n in nodes], dtype=float)
    for name, vector in (("work", work), ("true_change_bound", change), ("source", source)):
        if np.any(~np.isfinite(vector)) or np.any(vector < 0):
            raise ValueError(f"{name} must be finite and non-negative")
    return work, change, source


def _qois(payload: dict[str, Any], ids: dict[str, int]) -> list[QoI]:
    result: list[QoI] = []
    n = len(ids)
    for raw in payload.get("qois", []):
        R = np.zeros((1, n), dtype=float)
        for node, weight in raw.get("weights", {}).items():
            R[0, ids[str(node)]] = float(weight)
        result.append(QoI(str(raw["name"]), R, float(raw["epsilon"])))
    if not result:
        raise ValueError("graph requires at least one QoI")
    return result


def parse_graph(payload: dict[str, Any]) -> dict[str, Any]:
    ids = _node_index(payload)
    edges = _edges(payload, ids)
    work, change, source = _vectors(payload)
    hard = [ids[str(x)] for x in payload.get("hard_closure", [])]
    qois = _qois(payload, ids)
    return {
        "ids": ids,
        "edges": edges,
        "work": work,
        "change": change,
        "source": source,
        "hard": hard,
        "qois": qois,
        "K": certificate_transfer(len(ids), edges),
        "pred": exact_predecessors(len(ids), edges),
        "changed_fraction": float(payload.get("changed_fraction", 0.0)),
    }


def certify(parsed: dict[str, Any], cone: Iterable[int]) -> Certificate:
    return certify_cone(
        K_cert=parsed["K"],
        source=parsed["source"],
        true_change_bound=parsed["change"],
        cone=cone,
        exact_predecessors=parsed["pred"],
        work=parsed["work"],
        qois=parsed["qois"],
    )


def outward_radius(
    node_count: int,
    edges: list[RevisionEdge],
    seed: set[int],
    radius: int,
) -> set[int]:
    if radius < 0:
        raise ValueError("radius must be non-negative")
    adjacency = [set() for _ in range(node_count)]
    for edge in edges:
        adjacency[edge.src].add(edge.dst)
    selected = set(seed)
    frontier = set(seed)
    for _ in range(radius):
        next_frontier: set[int] = set()
        for node in frontier:
            next_frontier.update(adjacency[node])
        next_frontier -= selected
        selected.update(next_frontier)
        frontier = next_frontier
        if not frontier:
            break
    return selected


def empirical_ordered_cone(parsed: dict[str, Any]) -> Certificate:
    n = len(parsed["ids"])
    cone = predecessor_closure(parsed["hard"], parsed["pred"], n)
    current = certify(parsed, cone)
    if current.passes:
        return current

    priority = empirical_priority(n, parsed["edges"])
    # Conservative scheduling only: certification remains analytic/exact.
    score = priority.sum(axis=0) + priority.sum(axis=1)
    remaining = [i for i in range(n) if i not in cone]
    remaining.sort(key=lambda i: (-float(score[i]), float(parsed["work"][i]), i))
    for node in remaining:
        cone = predecessor_closure(cone | {node}, parsed["pred"], n)
        current = certify(parsed, cone)
        if current.passes:
            return current
    return certify(parsed, range(n))


def selection_methods(parsed: dict[str, Any], fraction_threshold: float = 0.1) -> dict[str, Certificate]:
    n = len(parsed["ids"])
    exact = predecessor_closure(parsed["hard"], parsed["pred"], n)

    result: dict[str, Certificate] = {
        "FULL": certify(parsed, range(n)),
        "EXACT": certify(parsed, exact),
    }
    for radius in range(4):
        cone = outward_radius(n, parsed["edges"], exact, radius)
        cone = predecessor_closure(cone, parsed["pred"], n)
        result[f"RADIUS_{radius}"] = certify(parsed, cone)

    fraction_cone = (
        set(range(n))
        if parsed["changed_fraction"] >= fraction_threshold
        else exact
    )
    result["FRACTION"] = certify(parsed, fraction_cone)
    result["EMPIRICAL"] = empirical_ordered_cone(parsed)
    result["CBRC"] = greedy_minimum_work_cone(
        K_cert=parsed["K"],
        source=parsed["source"],
        true_change_bound=parsed["change"],
        hard_closure=parsed["hard"],
        exact_predecessors=parsed["pred"],
        work=parsed["work"],
        qois=parsed["qois"],
    )
    return result


def ablations(payload: dict[str, Any]) -> dict[str, Certificate]:
    parsed = parse_graph(payload)
    n = len(parsed["ids"])
    result: dict[str, Certificate] = {}

    # A1: predecessor closure removed. Selection starts only from declared hard
    # seed while certification intentionally uses no exact predecessor rules.
    no_pred = dict(parsed)
    no_pred["pred"] = [set() for _ in range(n)]
    result["ABLATE_PREDECESSOR_CLOSURE"] = greedy_minimum_work_cone(
        K_cert=no_pred["K"],
        source=no_pred["source"],
        true_change_bound=no_pred["change"],
        hard_closure=no_pred["hard"],
        exact_predecessors=no_pred["pred"],
        work=no_pred["work"],
        qois=no_pred["qois"],
    )

    # A2/A3: remove analytic Gaussian or temporal theorem. Fail closed by
    # promoting those edges to exact dependencies.
    for label, token in (
        ("ABLATE_GAUSSIAN_ANALYTIC_BOUND", "gaussian"),
        ("ABLATE_TEMPORAL_ANALYTIC_BOUND", "temporal"),
    ):
        edges: list[RevisionEdge] = []
        for edge in parsed["edges"]:
            if (
                edge.edge_class is EdgeClass.ANALYTIC
                and edge.bound_id
                and token in edge.bound_id.lower()
            ):
                edges.append(
                    RevisionEdge(
                        edge.src,
                        edge.dst,
                        EdgeClass.HARD,
                        None,
                        None,
                    )
                )
            else:
                edges.append(edge)
        mutated = dict(parsed)
        mutated["K"] = certificate_transfer(n, edges)
        mutated["pred"] = exact_predecessors(n, edges)
        result[label] = greedy_minimum_work_cone(
            K_cert=mutated["K"],
            source=mutated["source"],
            true_change_bound=mutated["change"],
            hard_closure=mutated["hard"],
            exact_predecessors=mutated["pred"],
            work=mutated["work"],
            qois=mutated["qois"],
        )

    # A4: no QoI specialization. Every state block contributes unit weight to
    # one global envelope with the strictest declared epsilon.
    global_R = np.ones((1, n), dtype=float)
    global_qoi = [
        QoI(
            "global-state-envelope",
            global_R,
            min(q.epsilon for q in parsed["qois"]),
        )
    ]
    result["ABLATE_QOI_SPECIALIZATION"] = greedy_minimum_work_cone(
        K_cert=parsed["K"],
        source=parsed["source"],
        true_change_bound=parsed["change"],
        hard_closure=parsed["hard"],
        exact_predecessors=parsed["pred"],
        work=parsed["work"],
        qois=global_qoi,
    )

    # A5: no certified fallback. Return exact closure even if it fails; this is
    # intentionally expected to expose unsafe cases.
    result["ABLATE_NO_FALLBACK"] = certify(
        parsed,
        predecessor_closure(parsed["hard"], parsed["pred"], n),
    )
    return result


def certificate_dict(method: str, certificate: Certificate) -> dict[str, Any]:
    return {
        "method": method,
        "cone": list(certificate.cone),
        "exterior": list(certificate.exterior),
        "stable": certificate.stable,
        "passes": certificate.passes,
        "reason": certificate.reason,
        "bounds": certificate.bound_by_qoi,
        "work": certificate.work,
        "fullWork": certificate.full_work,
        "workRatioFull": (
            None
            if certificate.full_work == 0.0
            else certificate.work / certificate.full_work
        ),
        "usedFullRebuild": certificate.used_full_rebuild,
        "transientAmplification": certificate.transient_amplification,
        "susceptibility": certificate.susceptibility,
    }


def run(payload: dict[str, Any]) -> dict[str, Any]:
    parsed = parse_graph(payload)
    methods = selection_methods(parsed)
    abs_ = ablations(payload)
    return {
        "schemaVersion": 1,
        "experiment": "cbrc-baseline-ablation-suite-v1",
        "baselines": {
            name: certificate_dict(name, cert)
            for name, cert in methods.items()
        },
        "ablations": {
            name: certificate_dict(name, cert)
            for name, cert in abs_.items()
        },
        "safetyRule": (
            "Selection strategy never bypasses certificate validation. "
            "passes=false rows remain in the result."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(json.loads(args.input.read_text()))
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        tmp = args.output.with_suffix(args.output.suffix + ".tmp")
        tmp.write_text(text)
        tmp.replace(args.output)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
