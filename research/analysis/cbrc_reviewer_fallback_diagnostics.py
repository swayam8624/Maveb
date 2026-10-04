#!/usr/bin/env python3
"""Diagnose why reviewer-v2 cases selected FULL instead of LOCAL.

This is a read-only post-hoc diagnostic. It never changes the frozen campaign,
case outputs, thresholds, or readiness gates.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


TOL = 1e-12


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError("JSONL row must be an object")
            rows.append(payload)
    if not rows:
        raise ValueError("diagnostic requires at least one campaign row")
    return rows


def safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator <= 0.0:
        return None
    return numerator / denominator


def case_manifest(campaign_dir: Path | None, case_id: str) -> dict[str, Any] | None:
    if campaign_dir is None:
        return None
    path = campaign_dir / "cases" / case_id / "replay-manifest.json"
    if not path.is_file():
        return None
    return load_json(path)


def classify_row(
    row: dict[str, Any],
    *,
    manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    case_id = str(row.get("case_id", ""))
    qoi = row["qois"]["rgb_linf"]
    epsilon = float(qoi["epsilon"])
    fallback = bool(row.get("fallback_full", False))
    full_work = float(row.get("full_work", 0.0))
    diagnostics = row.get("candidateDiagnostics", {})
    if not isinstance(diagnostics, dict):
        diagnostics = {}

    candidate_bound = float(diagnostics.get("candidateRgbBound", 0.0))
    candidate_actual = float(diagnostics.get("candidateActualRgbError", 0.0))
    candidate_work = float(diagnostics.get("candidateWork", full_work))
    source_bound = float(diagnostics.get("sourceEditRgbBound", 0.0))
    repair_bound = float(diagnostics.get("postRepairResidualBound", 0.0))

    production: dict[str, Any] = {}
    production_root: dict[str, Any] = {}
    if manifest is not None:
        production_root = manifest.get("production_certificate", {})
        if not isinstance(production_root, dict):
            production_root = {}
        production = production_root.get("outputConePlanner", {})
        if not isinstance(production, dict):
            production = {}

    production_full = (
        bool(production.get("fullRepair")) if production else None
    )
    temporal_repair_selected = (
        bool(production.get("temporalRepairSelected")) if production else None
    )
    temporal_full_frame = (
        bool(production_root.get("temporalFullFrameFallback"))
        if production_root
        else None
    )
    history_weight = (
        float(production.get("historyWeight", 0.0)) if production else None
    )
    temporal_repair_work = (
        float(production.get("temporalRepairWork", 0.0)) if production else None
    )
    production_full_work = (
        float(production.get("fullWork", full_work)) if production else None
    )
    production_resolved_bound = (
        float(production.get("resolvedRgbBound", 0.0))
        if production
        else float(diagnostics.get("productionResolvedRgbBound", 0.0))
    )

    no_history_repair_bound = (
        history_weight * source_bound if history_weight is not None else None
    )
    temporal_work_ratio = (
        safe_ratio(temporal_repair_work, production_full_work)
        if temporal_repair_work is not None and production_full_work is not None
        else None
    )

    if not fallback:
        cause = "local-selected"
    elif production_full is True:
        if temporal_full_frame is True or (
            temporal_work_ratio is not None and temporal_work_ratio >= 1.0 - TOL
        ):
            cause = "production-full-full-frame-temporal-support"
        else:
            cause = "production-full-other"
    elif candidate_bound > epsilon + TOL:
        cause = "post-repair-certified-bound-over-epsilon"
    elif candidate_actual > epsilon + TOL:
        cause = "post-repair-measured-error-over-epsilon"
    elif candidate_work >= full_work - TOL:
        cause = "candidate-has-no-work-saving"
    else:
        cause = "unexplained-full-fallback"

    return {
        "caseId": case_id,
        "dataset": str(row.get("dataset_id", "unknown")),
        "editFamily": str(row.get("edit_family", row.get("edit_class", "unknown"))),
        "epsilon": epsilon,
        "fallbackFull": fallback,
        "cause": cause,
        "candidateBound": candidate_bound,
        "candidateActual": candidate_actual,
        "candidateWork": candidate_work,
        "fullWork": full_work,
        "candidateWorkRatioFull": safe_ratio(candidate_work, full_work),
        "sourceEditRgbBound": source_bound,
        "postRepairResidualBound": repair_bound,
        "productionResolvedRgbBound": production_resolved_bound,
        "productionFullRepair": production_full,
        "temporalRepairSelected": temporal_repair_selected,
        "temporalFullFrameFallback": temporal_full_frame,
        "historyWeight": history_weight,
        "noHistoryRepairBound": no_history_repair_bound,
        "noHistoryRepairBoundToEpsilon": (
            safe_ratio(no_history_repair_bound, epsilon)
            if no_history_repair_bound is not None
            else None
        ),
        "temporalRepairWork": temporal_repair_work,
        "productionFullWork": production_full_work,
        "temporalRepairWorkRatioFull": temporal_work_ratio,
        "manifestResolved": manifest is not None,
    }


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    causes = Counter(record["cause"] for record in records)
    fallback = [record for record in records if record["fallbackFull"]]
    production_full = [
        record for record in records if record["productionFullRepair"] is True
    ]
    full_frame = [
        record for record in records if record["temporalFullFrameFallback"] is True
    ]
    full_temporal_cost = [
        record
        for record in records
        if record["temporalRepairWorkRatioFull"] is not None
        and record["temporalRepairWorkRatioFull"] >= 1.0 - TOL
    ]
    no_history_over = [
        record
        for record in records
        if record["noHistoryRepairBound"] is not None
        and record["noHistoryRepairBound"] > record["epsilon"] + TOL
    ]

    by_dataset: dict[str, Counter[str]] = defaultdict(Counter)
    by_family: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        by_dataset[record["dataset"]][record["cause"]] += 1
        by_family[record["editFamily"]][record["cause"]] += 1

    return {
        "schemaVersion": 1,
        "artifact": "maveb-reviewer-v2-fallback-diagnostics",
        "readOnlyDiagnostic": True,
        "recordCount": len(records),
        "fallbackCases": len(fallback),
        "localCases": len(records) - len(fallback),
        "manifestResolvedCases": sum(record["manifestResolved"] for record in records),
        "fallbackCauseCounts": dict(sorted(causes.items())),
        "productionFullRepairCases": len(production_full),
        "temporalFullFrameFallbackCases": len(full_frame),
        "temporalRepairCostEqualsFullCases": len(full_temporal_cost),
        "noHistoryRepairBoundOverEpsilonCases": len(no_history_over),
        "allFallbacksExplained": all(
            record["cause"] != "unexplained-full-fallback" for record in fallback
        ),
        "byDataset": {
            key: dict(sorted(value.items())) for key, value in sorted(by_dataset.items())
        },
        "byEditFamily": {
            key: dict(sorted(value.items())) for key, value in sorted(by_family.items())
        },
        "interpretation": (
            "This report diagnoses the already-frozen reviewer-v2 execution. "
            "It must not be used to delete, retune, or relabel cases. "
            "A production-full-full-frame-temporal-support result means the native "
            "output-cone planner selected FULL while the certified temporal repair "
            "support/cost covered the whole frame; it is evidence about the current "
            "certificate/support model, not permission to modify reviewer-v2."
        ),
        "records": records,
    }


def analyze(rows: list[dict[str, Any]], campaign_dir: Path | None) -> dict[str, Any]:
    records = [
        classify_row(
            row,
            manifest=case_manifest(campaign_dir, str(row.get("case_id", ""))),
        )
        for row in rows
    ]
    return summarize(records)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument(
        "--campaign-dir",
        type=Path,
        help="Campaign execution root containing cases/<case-id>/replay-manifest.json",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    rows_path = args.rows.resolve()
    campaign_dir = args.campaign_dir.resolve() if args.campaign_dir else None
    report = analyze(load_jsonl(rows_path), campaign_dir)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
