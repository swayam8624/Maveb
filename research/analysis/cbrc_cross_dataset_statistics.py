#!/usr/bin/env python3
"""Cross-dataset statistical analysis for frozen MAVEB CBRC campaigns."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

DEFAULT_SEED = 20260922


def rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * q
    lo, hi = math.floor(index), math.ceil(index)
    if lo == hi:
        return values[lo]
    alpha = index - lo
    return values[lo] * (1.0 - alpha) + values[hi] * alpha


def bootstrap_median_ci(
    values: list[float], *, iterations: int, seed: int
) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    if len(values) == 1:
        return values[0], values[0]
    rng = random.Random(seed)
    n = len(values)
    medians = []
    for _ in range(iterations):
        medians.append(statistics.median(values[rng.randrange(n)] for _ in range(n)))
    return percentile(medians, 0.025), percentile(medians, 0.975)


def wilson(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    if total <= 0:
        return None, None
    p = successes / total
    denominator = 1.0 + z * z / total
    center = (p + z * z / (2.0 * total)) / denominator
    half = z * math.sqrt(p * (1.0 - p) / total + z * z / (4.0 * total * total)) / denominator
    return max(0.0, center - half), min(1.0, center + half)


def contract_violation(row: dict[str, Any]) -> bool:
    for qoi in (row.get("qois") or {}).values():
        actual = float(qoi["measured_full_reference_error"])
        bound = float(qoi["certified_bound"])
        epsilon = float(qoi["epsilon"])
        if actual > bound + 1e-12 or bound > epsilon + 1e-12:
            return True
    return False


def ratio(row: dict[str, Any]) -> float | None:
    full = float(row.get("full_work", 0.0))
    if full <= 0.0:
        return None
    return float(row["planner_work"]) / full


def summarize_group(
    group: list[dict[str, Any]], *, iterations: int, seed: int
) -> dict[str, Any]:
    ratios = [value for row in group if (value := ratio(row)) is not None]
    local = sum(not bool(row.get("fallback_full", False)) for row in group)
    fallbacks = len(group) - local
    violations = sum(contract_violation(row) for row in group)
    local_ci = wilson(local, len(group))
    violation_ci = wilson(violations, len(group))
    median_ci = bootstrap_median_ci(ratios, iterations=iterations, seed=seed)
    return {
        "cases": len(group),
        "scenes": len({str(row.get("source_scene_id") or row.get("scene_id")) for row in group}),
        "localCases": local,
        "fullFallbackCases": fallbacks,
        "localRate": local / len(group) if group else None,
        "localRate95CI": list(local_ci),
        "certificateViolations": violations,
        "violationRate": violations / len(group) if group else None,
        "violationRate95CI": list(violation_ci),
        "workRatioFull": {
            "median": statistics.median(ratios) if ratios else None,
            "q1": percentile(ratios, 0.25),
            "q3": percentile(ratios, 0.75),
            "minimum": min(ratios) if ratios else None,
            "maximum": max(ratios) if ratios else None,
            "bootstrapMedian95CI": list(median_ci),
        },
    }


def exact_sign_test(wins: int, losses: int) -> float | None:
    n = wins + losses
    if n == 0:
        return None
    tail = min(wins, losses)
    probability = sum(math.comb(n, k) for k in range(tail + 1)) / (2 ** n)
    return min(1.0, 2.0 * probability)


def baseline_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    paired: dict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for record in records:
        cbrc = (record.get("baselines") or {}).get("CBRC")
        if not isinstance(cbrc, dict):
            continue
        for family in ("baselines", "ablations"):
            for name, other in (record.get(family) or {}).items():
                if name == "CBRC" or not isinstance(other, dict):
                    continue
                paired[(family, name)].append((cbrc, other))

    output: dict[str, Any] = {"baselines": {}, "ablations": {}}
    for (family, name), values in sorted(paired.items()):
        both_pass = [
            (float(c["workRatioFull"]), float(o["workRatioFull"]))
            for c, o in values
            if c.get("passes")
            and o.get("passes")
            and c.get("workRatioFull") is not None
            and o.get("workRatioFull") is not None
        ]
        deltas = [other - cbrc for cbrc, other in both_pass]
        wins = sum(delta > 1e-12 for delta in deltas)
        losses = sum(delta < -1e-12 for delta in deltas)
        ties = len(deltas) - wins - losses
        output[family][name] = {
            "pairedCases": len(values),
            "cbrcCertificatePasses": sum(bool(c.get("passes")) for c, _ in values),
            "comparisonCertificatePasses": sum(bool(o.get("passes")) for _, o in values),
            "bothCertifiedCases": len(both_pass),
            "medianOtherMinusCbrcWorkRatio": statistics.median(deltas) if deltas else None,
            "cbrcLowerWorkCasesAmongBothCertified": wins,
            "comparisonLowerWorkCasesAmongBothCertified": losses,
            "tiesAmongBothCertified": ties,
            "exactTwoSidedSignTestP": exact_sign_test(wins, losses),
        }
    return output


def grouped(rows_: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows_:
        value = row.get(key)
        result[str(value if value not in (None, "") else "unknown")].append(row)
    return dict(result)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--baselines", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    if args.bootstrap_iterations < 100:
        parser.error("--bootstrap-iterations must be >= 100")

    campaign_rows = rows(args.rows.resolve())
    if not campaign_rows:
        raise SystemExit("no campaign rows")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    overall = summarize_group(
        campaign_rows,
        iterations=args.bootstrap_iterations,
        seed=args.seed,
    )
    dimensions = {}
    for dimension in (
        "dataset_id",
        "representation",
        "edit_family",
        "coupling_regime",
    ):
        dimensions[dimension] = {
            name: summarize_group(
                values,
                iterations=args.bootstrap_iterations,
                seed=args.seed + index + len(name),
            )
            for index, (name, values) in enumerate(sorted(grouped(campaign_rows, dimension).items()))
        }

    baseline_payload = (
        baseline_stats(rows(args.baselines.resolve()))
        if args.baselines and args.baselines.is_file()
        else None
    )
    dataset_groups = dimensions["dataset_id"]
    result = {
        "schemaVersion": 1,
        "artifact": "maveb-cbrc-cross-dataset-statistics",
        "cases": len(campaign_rows),
        "datasetCount": len(dataset_groups),
        "algorithmFreezeAssumption": (
            "All rows are interpreted as one frozen algorithm/threshold campaign. "
            "Do not combine rows from independently retuned runs."
        ),
        "overall": overall,
        "by": dimensions,
        "pairedBaselineStatistics": baseline_payload,
        "crossDatasetGates": {
            "atLeastThreeDatasets": len(dataset_groups) >= 3,
            "allDatasetsHaveCases": all(group["cases"] > 0 for group in dataset_groups.values()),
            "zeroObservedCertificateViolations": overall["certificateViolations"] == 0,
            "bothLocalAndFallbackObserved": (
                overall["localCases"] > 0 and overall["fullFallbackCases"] > 0
            ),
        },
    }
    result["crossDatasetGates"]["pass"] = all(result["crossDatasetGates"].values())
    write_json(output / "CROSS_DATASET_STATISTICS.json", result)

    with (output / "dataset-summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "dataset",
                "cases",
                "scenes",
                "local_rate",
                "local_ci_low",
                "local_ci_high",
                "violations",
                "median_work_ratio_full",
                "work_ci_low",
                "work_ci_high",
            ]
        )
        for name, summary in sorted(dataset_groups.items()):
            writer.writerow(
                [
                    name,
                    summary["cases"],
                    summary["scenes"],
                    summary["localRate"],
                    *summary["localRate95CI"],
                    summary["certificateViolations"],
                    summary["workRatioFull"]["median"],
                    *summary["workRatioFull"]["bootstrapMedian95CI"],
                ]
            )

    lines = [
        "# MAVEB cross-dataset CBRC statistics",
        "",
        f"- Cases: **{len(campaign_rows)}**",
        f"- Datasets: **{len(dataset_groups)}**",
        f"- Observed certificate violations: **{overall['certificateViolations']}**",
        f"- LOCAL / FULL: **{overall['localCases']} / {overall['fullFallbackCases']}**",
        "",
        "| Dataset | Cases | Scenes | LOCAL rate | Violations | Median work/FULL | 95% bootstrap CI |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, summary in sorted(dataset_groups.items()):
        median = summary["workRatioFull"]["median"]
        ci = summary["workRatioFull"]["bootstrapMedian95CI"]
        lines.append(
            f"| {name} | {summary['cases']} | {summary['scenes']} | "
            f"{summary['localRate']:.3f} | {summary['certificateViolations']} | "
            f"{median:.5f} | [{ci[0]:.5f}, {ci[1]:.5f}] |"
            if median is not None and ci[0] is not None
            else f"| {name} | {summary['cases']} | {summary['scenes']} | "
            f"{summary['localRate']:.3f} | {summary['certificateViolations']} | — | — |"
        )
    lines.extend(
        [
            "",
            "These are empirical cross-dataset results under the frozen campaign contract, not a universal proof.",
            "",
        ]
    )
    (output / "CROSS_DATASET_STATISTICS.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["crossDatasetGates"]["pass"] else 5


if __name__ == "__main__":
    raise SystemExit(main())
