#!/usr/bin/env python3
"""Purpose-built mechanism-isolation stress cases for the CBRC ablations.

These cases are synthetic by design. They do not replace the frozen real-scene
campaign. Their only purpose is to make individual safety mechanisms
falsifiable when the real campaign happens to be non-discriminative.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from research.experiments.cbrc_baseline_suite import run as run_suite


def node(
    name: str,
    work: float,
    change: float = 0.0,
    source: float = 0.0,
) -> dict[str, Any]:
    return {
        "id": name,
        "work": work,
        "true_change_bound": change,
        "source_bound": source,
    }


def edge(
    source: str,
    target: str,
    cls: str,
    *,
    gain: float | None = None,
    bound_id: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"source": source, "target": target, "class": cls}
    if gain is not None:
        result["gain"] = gain
    if bound_id is not None:
        result["bound_id"] = bound_id
    return result


def qoi(name: str, weights: dict[str, float], epsilon: float) -> dict[str, Any]:
    return {"name": name, "weights": weights, "epsilon": epsilon}


def chain_graph() -> dict[str, Any]:
    return {
        "nodes": [
            node("edit", 1.0, change=1.0, source=1.0),
            node("middle", 1.0, change=0.5),
            node("output", 10.0),
        ],
        "edges": [
            edge(
                "edit",
                "middle",
                "analytic",
                gain=0.2,
                bound_id="gaussian-image-v1",
            ),
            edge(
                "middle",
                "output",
                "analytic",
                gain=0.2,
                bound_id="temporal-v1",
            ),
        ],
        "hard_closure": ["edit"],
        "qois": [qoi("rgb", {"output": 1.0}, 0.1)],
        "changed_fraction": 0.01,
    }


def predecessor_graph() -> dict[str, Any]:
    return {
        "nodes": [
            node("provenance", 4.0),
            node("edit", 1.0, change=1.0, source=0.0),
            node("output", 2.0),
        ],
        "edges": [
            edge("provenance", "edit", "hard"),
            edge(
                "edit",
                "output",
                "analytic",
                gain=0.01,
                bound_id="gaussian-image-v1",
            ),
        ],
        "hard_closure": ["edit"],
        "qois": [qoi("rgb", {"output": 1.0}, 0.05)],
        "changed_fraction": 0.01,
    }


def temporal_graph() -> dict[str, Any]:
    return {
        "nodes": [
            node("edit", 1.0, change=1.0, source=0.0),
            node("current", 1.0),
            node("history", 8.0),
        ],
        "edges": [
            edge("edit", "current", "hard"),
            edge(
                "current",
                "history",
                "analytic",
                gain=0.02,
                bound_id="temporal-v1",
            ),
        ],
        "hard_closure": ["edit"],
        "qois": [qoi("resolved-rgb", {"history": 1.0}, 0.05)],
        "changed_fraction": 0.01,
    }


def qoi_specialization_graph() -> dict[str, Any]:
    return {
        "nodes": [
            node("edit", 1.0, change=1.0, source=0.0),
            node("protected-output", 2.0),
            node("irrelevant-state", 20.0, source=0.2),
        ],
        "edges": [
            edge(
                "edit",
                "protected-output",
                "analytic",
                gain=0.01,
                bound_id="gaussian-image-v1",
            ),
        ],
        "hard_closure": ["edit"],
        "qois": [qoi("protected-rgb", {"protected-output": 1.0}, 0.05)],
        "changed_fraction": 0.01,
    }


def structured_tail_graph() -> dict[str, Any]:
    return {
        "nodes": [
            node("edit", 1.0, change=1.0, source=0.0),
            node("left", 2.0),
            node("right", 2.0),
            node("merge", 20.0),
        ],
        "edges": [
            edge(
                "edit",
                "left",
                "analytic",
                gain=0.1,
                bound_id="gaussian-image-v1",
            ),
            edge(
                "edit",
                "right",
                "analytic",
                gain=0.1,
                bound_id="gaussian-image-v1",
            ),
            edge(
                "left",
                "merge",
                "analytic",
                gain=0.6,
                bound_id="temporal-v1",
            ),
            edge(
                "right",
                "merge",
                "analytic",
                gain=0.6,
                bound_id="temporal-v1",
            ),
        ],
        "hard_closure": ["edit"],
        "qois": [qoi("rgb", {"merge": 1.0}, 0.2)],
        "changed_fraction": 0.01,
    }


def record(
    mechanism: str,
    graph: dict[str, Any],
    ablation: str,
    expectation: str,
) -> dict[str, Any]:
    result = run_suite(graph)
    cbrc = result["baselines"]["CBRC"]
    ablated = result["ablations"][ablation]
    separated = (
        bool(cbrc["passes"])
        and (
            not bool(ablated["passes"])
            or float(ablated["work"]) > float(cbrc["work"]) + 1e-12
            or (
                bool(ablated["usedFullRebuild"])
                and not bool(cbrc["usedFullRebuild"])
            )
        )
    )
    return {
        "mechanism": mechanism,
        "ablation": ablation,
        "expectation": expectation,
        "separated": separated,
        "cbrc": {
            "passes": cbrc["passes"],
            "work": cbrc["work"],
            "fullWork": cbrc["fullWork"],
            "usedFullRebuild": cbrc["usedFullRebuild"],
        },
        "ablated": {
            "passes": ablated["passes"],
            "work": ablated["work"],
            "fullWork": ablated["fullWork"],
            "usedFullRebuild": ablated["usedFullRebuild"],
            "reason": ablated["reason"],
        },
    }


def run() -> dict[str, Any]:
    cases = [
        record(
            "exact predecessor closure",
            predecessor_graph(),
            "ABLATE_PREDECESSOR_CLOSURE",
            "Removing exact predecessor closure must either fail or appear cheaper only by omitting required exact work.",
        ),
        record(
            "Gaussian analytic soft bound",
            chain_graph(),
            "ABLATE_GAUSSIAN_ANALYTIC_BOUND",
            "Promoting the Gaussian analytic edge to HARD should increase selected work or force FULL.",
        ),
        record(
            "temporal analytic soft bound",
            temporal_graph(),
            "ABLATE_TEMPORAL_ANALYTIC_BOUND",
            "Promoting the temporal analytic edge to HARD should increase selected work or force FULL.",
        ),
        record(
            "QoI specialization",
            qoi_specialization_graph(),
            "ABLATE_QOI_SPECIALIZATION",
            "Replacing the protected QoI with a global state envelope should require more work.",
        ),
        record(
            "HARD/ANALYTIC separation",
            chain_graph(),
            "ABLATE_HARD_SOFT_SEPARATION",
            "Collapsing every dependency to HARD should increase work or force FULL.",
        ),
        record(
            "graph-structured exterior response",
            structured_tail_graph(),
            "ABLATE_GLOBAL_NORM_TAIL",
            "A global infinity-norm tail should be strictly more conservative on a DAG with row-sum fan-in above one.",
        ),
        record(
            "certified fallback",
            chain_graph(),
            "ABLATE_NO_FALLBACK",
            "Suppressing certified expansion/fallback should leave an unsafe exact-closure candidate failing certification.",
        ),
    ]
    passed = all(case["separated"] for case in cases)
    return {
        "schemaVersion": 1,
        "artifact": "maveb-cbrc-ablation-mechanism-stress",
        "syntheticMechanismIsolationOnly": True,
        "realCampaignReplacement": False,
        "cases": cases,
        "separatedMechanisms": sum(case["separated"] for case in cases),
        "mechanismCount": len(cases),
        "pass": passed,
        "interpretation": (
            "PASS means every required v1 mechanism has at least one deterministic "
            "synthetic stress case where removing that mechanism worsens safety or "
            "certified work. It does not establish real-world effect size."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run()
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    else:
        print(text, end="")
    return 0 if result["pass"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
