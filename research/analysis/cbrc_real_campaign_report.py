#!/usr/bin/env python3
"""Generate an answer-first report from a completed real CBRC campaign."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def median(values: list[float]) -> float | None:
    return None if not values else statistics.median(values)


def fmt(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.6g}"


def summarize(results_dir: Path) -> dict[str, Any]:
    rows = load_jsonl(results_dir / "campaign-rows.jsonl")
    gates = load_json(results_dir / "campaign-gates.json")
    evaluation = load_json(results_dir / "campaign-evaluation.json")
    baselines = load_json(results_dir / "baseline-summary.json")

    local_rows = [row for row in rows if not bool(row.get("fallback_full", False))]
    fallback_rows = [row for row in rows if bool(row.get("fallback_full", False))]
    work_ratios = []
    effectivities = []
    actuals = []
    bounds = []
    units = set()
    model_versions = set()
    domain_ratios: dict[str, list[float]] = defaultdict(list)

    for row in rows:
        full_work = float(row.get("full_work", 0.0))
        planner_work = float(row.get("planner_work", 0.0))
        if full_work > 0.0:
            work_ratios.append(planner_work / full_work)
        units.add(str(row.get("work_cost_unit", "")))
        model_versions.add(str(row.get("work_cost_model_version", "")))

        qoi = row.get("qois", {}).get("rgb_linf", {})
        actual = float(qoi.get("measured_full_reference_error", 0.0))
        bound = float(qoi.get("certified_bound", 0.0))
        actuals.append(actual)
        bounds.append(bound)

        diagnostics = row.get("candidateDiagnostics", {})
        effectivity = float(diagnostics.get("effectivity", float("nan")))
        if math.isfinite(effectivity):
            effectivities.append(effectivity)

        domains = row.get("work_ledger", {}).get("domains", {})
        if isinstance(domains, dict):
            for name, counter in domains.items():
                if not isinstance(counter, dict):
                    continue
                full = float(counter.get("full", 0.0))
                incremental = float(counter.get("incremental", 0.0))
                if full > 0.0:
                    domain_ratios[str(name)].append(incremental / full)

    calibrated_ms = units == {"ms"}
    return {
        "schemaVersion": 1,
        "artifact": "maveb-cbrc-real-campaign-answer",
        "campaignPass": bool(gates.get("pass", False)) and bool(evaluation.get("pass", False)),
        "rows": len(rows),
        "scenes": len({str(row.get("scene_id", "")) for row in rows}),
        "certifiedLocalCases": len(local_rows),
        "fullFallbackCases": len(fallback_rows),
        "certificateViolations": len(gates.get("certificateViolations", [])),
        "medianSelectedWorkRatioFull": median(work_ratios),
        "medianWorkReductionFactor": (
            None
            if not work_ratios or median(work_ratios) in (None, 0.0)
            else 1.0 / float(median(work_ratios))
        ),
        "medianCandidateEffectivity": median(effectivities),
        "maximumMeasuredSelectedError": max(actuals, default=None),
        "maximumSelectedCertifiedBound": max(bounds, default=None),
        "workCostUnits": sorted(units),
        "workCostModelVersions": sorted(model_versions),
        "heterogeneousMsCalibrationUsed": calibrated_ms,
        "medianNativeDomainRatios": {
            name: statistics.median(values)
            for name, values in sorted(domain_ratios.items())
            if values
        },
        "gates": gates.get("gates", {}),
        "baselineSummary": baselines,
        "interpretationBoundary": (
            "heterogeneous millisecond-calibrated work"
            if calibrated_ms
            else (
                "native single-domain/output work plus per-domain ratios; "
                "do not describe this as heterogeneous wall-clock speedup"
            )
        ),
    }


def markdown(summary: dict[str, Any]) -> str:
    status = "PASS" if summary["campaignPass"] else "FAIL"
    lines = [
        "# MAVEB CBRC real-campaign answer",
        "",
        f"**Evidence gate:** {status}",
        "",
        f"- Real revision rows: {summary['rows']}",
        f"- Scenes: {summary['scenes']}",
        f"- Certified local cases: {summary['certifiedLocalCases']}",
        f"- Automatic FULL fallbacks: {summary['fullFallbackCases']}",
        f"- Certificate violations: {summary['certificateViolations']}",
        f"- Median selected work / FULL: {fmt(summary['medianSelectedWorkRatioFull'])}",
        f"- Median work-reduction factor: {fmt(summary['medianWorkReductionFactor'])}x",
        f"- Median candidate effectivity: {fmt(summary['medianCandidateEffectivity'])}",
        f"- Maximum measured selected error: {fmt(summary['maximumMeasuredSelectedError'])}",
        f"- Maximum selected certified bound: {fmt(summary['maximumSelectedCertifiedBound'])}",
        "",
        "## Native-domain work ratios",
        "",
    ]
    for name, ratio in summary["medianNativeDomainRatios"].items():
        lines.append(f"- {name}: {ratio:.6g} of FULL")

    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            summary["interpretationBoundary"],
            "",
            "A publishable safety claim requires zero certificate violations. "
            "A heterogeneous latency/work claim requires a frozen millisecond cost model; "
            "otherwise report the native single-domain work and domain ratios separately.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    args = parser.parse_args()

    summary = summarize(args.results_dir)
    json_path = args.output_json or args.results_dir / "REAL_CAMPAIGN_ANSWER.json"
    md_path = args.output_md or args.results_dir / "REAL_CAMPAIGN_ANSWER.md"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    md_path.write_text(markdown(summary))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["campaignPass"] else 5


if __name__ == "__main__":
    raise SystemExit(main())
