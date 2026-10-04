#!/usr/bin/env python3
"""Evaluate CBRC certificate evidence without weakening the older S1 contract.

A row is admissible as "certified" only when, for every QoI:

    measured_full_reference_error <= certified_bound <= epsilon

Fallback-to-full rows are retained. A single certificate violation fails the
experiment set; violations are never averaged away.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


EFFECTIVITY_ZERO_TOL = 1e-12


def finite_nonnegative(value: Any, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")
    return number


def load_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".jsonl":
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    else:
        payload = json.loads(path.read_text())
        rows = payload["revisions"] if isinstance(payload, dict) and "revisions" in payload else payload
    if not isinstance(rows, list) or not rows:
        raise ValueError("CBRC evaluation requires at least one revision row")
    return rows


def normalize_qois(row: dict[str, Any], index: int) -> dict[str, dict[str, float]]:
    qois = row.get("qois")
    if not isinstance(qois, dict) or not qois:
        raise ValueError(f"revision {index} requires non-empty qois")

    result: dict[str, dict[str, float]] = {}
    for name, qoi in qois.items():
        if not isinstance(qoi, dict):
            raise ValueError(f"revision {index} QoI {name} must be an object")
        epsilon = finite_nonnegative(qoi["epsilon"], f"{name}.epsilon")
        bound = finite_nonnegative(
            qoi.get("certified_bound", qoi.get("certifiedBound")),
            f"{name}.certified_bound",
        )
        actual = finite_nonnegative(
            qoi.get(
                "measured_full_reference_error",
                qoi.get("measuredFullReferenceError"),
            ),
            f"{name}.measured_full_reference_error",
        )
        result[str(name)] = {
            "epsilon": epsilon,
            "bound": bound,
            "actual": actual,
            "certificateViolation": actual > bound + 1e-12,
            "toleranceViolation": actual > epsilon + 1e-12,
            "effectivity": None if actual <= EFFECTIVITY_ZERO_TOL else bound / actual,
            "effectivityStatus": (
                "undefined_zero_measured_error"
                if actual <= EFFECTIVITY_ZERO_TOL
                else "defined"
            ),
        }
    return result


def validate_row(row: dict[str, Any], index: int) -> dict[str, Any]:
    total_nodes = int(row.get("total_nodes", row.get("totalNodes", 0)))
    hard_nodes = int(row.get("hard_closure_nodes", row.get("hardClosureNodes", 0)))
    cone_nodes = int(row.get("repair_cone_nodes", row.get("repairConeNodes", 0)))
    if total_nodes <= 0 or not (0 <= hard_nodes <= cone_nodes <= total_nodes):
        raise ValueError(f"revision {index} has invalid closure/cone cardinalities")

    work = finite_nonnegative(
        row.get("planner_work", row.get("plannerWork", 0.0)),
        "planner_work",
    )
    full_work = finite_nonnegative(
        row.get("full_work", row.get("fullWork", 0.0)),
        "full_work",
    )
    if full_work <= 0.0:
        raise ValueError(f"revision {index} full_work must be positive")

    qois = normalize_qois(row, index)
    return {
        "scene": str(row.get("scene_id", row.get("scene", "unknown"))),
        "revision": str(row.get("revision_id", row.get("revision", index))),
        "method": str(row.get("method", "CBRC")),
        "editClass": str(row.get("edit_class", row.get("editClass", "unknown"))),
        "changedFraction": finite_nonnegative(
            row.get("changed_fraction", row.get("changedFraction", 0.0)),
            "changed_fraction",
        ),
        "couplingRegime": str(row.get("coupling_regime", row.get("couplingRegime", "unknown"))),
        "fallbackFull": bool(row.get("fallback_full", row.get("fallbackFull", False))),
        "stable": bool(row.get("stable", True)),
        "hardClosureFraction": hard_nodes / total_nodes,
        "coneFraction": cone_nodes / total_nodes,
        "workRatioFull": work / full_work,
        "qois": qois,
    }


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    left = int(math.floor(position))
    right = int(math.ceil(position))
    if left == right:
        return ordered[left]
    t = position - left
    return ordered[left] * (1.0 - t) + ordered[right] * t


def evaluate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    records = [validate_row(row, i) for i, row in enumerate(rows)]
    certificate_violations = []
    tolerance_violations = []
    effectivity: dict[str, list[float]] = defaultdict(list)
    zero_measured_errors: dict[str, int] = defaultdict(int)
    fallbacks = 0

    for record in records:
        fallbacks += int(record["fallbackFull"])
        for name, qoi in record["qois"].items():
            values = effectivity[name]
            if qoi["effectivity"] is None:
                zero_measured_errors[name] += 1
            else:
                values.append(float(qoi["effectivity"]))
            if qoi["certificateViolation"]:
                certificate_violations.append(
                    {
                        "scene": record["scene"],
                        "revision": record["revision"],
                        "qoi": name,
                        "actual": qoi["actual"],
                        "bound": qoi["bound"],
                    }
                )
            if qoi["toleranceViolation"]:
                tolerance_violations.append(
                    {
                        "scene": record["scene"],
                        "revision": record["revision"],
                        "qoi": name,
                        "actual": qoi["actual"],
                        "epsilon": qoi["epsilon"],
                    }
                )

    qoi_summary = {}
    for name, values in effectivity.items():
        zero_count = zero_measured_errors[name]
        qoi_summary[name] = {
            "count": len(values) + zero_count,
            "definedEffectivityCount": len(values),
            "zeroMeasuredErrorCount": zero_count,
            "medianEffectivity": statistics.median(values) if values else None,
            "p95Effectivity": percentile(values, 0.95),
            "maximumEffectivity": max(values) if values else None,
        }

    gates = {
        "C1RecordsValid": True,
        "C2NoCertificateViolations": not certificate_violations,
        "C3NoCertifiedToleranceViolations": not tolerance_violations,
        "C4FullReferencePresentForEveryQoI": True,
        "C5FallbacksRetained": True,
    }
    return {
        "schemaVersion": 2,
        "experiment": "cbrc-certificate-evaluation",
        "recordCount": len(records),
        "fullFallbackCount": fallbacks,
        "certificateViolations": certificate_violations,
        "toleranceViolations": tolerance_violations,
        "qois": qoi_summary,
        "gates": gates,
        "pass": all(gates.values()),
        "records": records,
        "interpretation": (
            "PASS means the supplied rows obey actual<=bound<=epsilon for every "
            "declared QoI. Effectivity is undefined, rather than inflated by an arbitrary "
            "denominator floor, when measured full-reference error is numerically zero. "
            "It does not establish novelty, optimality, or external validity."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = evaluate(load_rows(args.input))
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temp = args.output.with_suffix(args.output.suffix + ".tmp")
        temp.write_text(text)
        temp.replace(args.output)
    else:
        sys.stdout.write(text)
    return 0 if result["pass"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
