#!/usr/bin/env python3
"""Trace a CBRC reviewer case from edit evidence to the final LOCAL/FULL decision.

This is read-only. It consumes frozen campaign outputs and never retunes epsilon,
edits, residual scales, cases, or production planner state.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


TOL = 1e-12


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows:
        raise ValueError("trace requires at least one campaign row")
    return rows


def ratio(a: float, b: float) -> float | None:
    return None if b <= 0.0 else a / b


def choose_case(rows: list[dict[str, Any]], requested: str | None) -> dict[str, Any]:
    if requested:
        for row in rows:
            if str(row.get("case_id", "")) == requested:
                return row
        raise ValueError(f"case not found: {requested}")
    fallback = [row for row in rows if bool(row.get("fallback_full", False))]
    pool = fallback or rows
    return max(
        pool,
        key=lambda row: (
            float(row.get("candidateDiagnostics", {}).get("candidateRgbBound", 0.0))
            / max(float(row["qois"]["rgb_linf"]["epsilon"]), 1e-30),
            str(row.get("case_id", "")),
        ),
    )


def trace_case(row: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    case_id = str(row.get("case_id", ""))
    qoi = row["qois"]["rgb_linf"]
    diagnostics = row.get("candidateDiagnostics", {})
    production = manifest.get("production_certificate", {})
    planner = production.get("outputConePlanner", {})
    temporal = production.get("temporal", {})
    publication = production.get("publication", {})

    epsilon = float(qoi["epsilon"])
    source_bound = float(diagnostics.get("sourceEditRgbBound", 0.0))
    source_actual = float(diagnostics.get("sourceEditActualRgbError", 0.0))
    resolved_bound = float(planner.get("resolvedRgbBound", diagnostics.get("productionResolvedRgbBound", 0.0)))
    residual_bound = float(diagnostics.get("postRepairResidualBound", 0.0))
    residual_actual = float(diagnostics.get("postRepairActualRgbError", 0.0))
    candidate_bound = float(diagnostics.get("candidateRgbBound", resolved_bound + residual_bound))
    candidate_actual = float(diagnostics.get("candidateActualRgbError", residual_actual))
    full_work = float(planner.get("fullWork", row.get("full_work", 0.0)))
    planner_work = float(planner.get("plannerWork", row.get("planner_work", full_work)))
    temporal_work = float(planner.get("temporalRepairWork", 0.0))
    history_weight = float(planner.get("historyWeight", 0.0))
    temporal_full_frame = bool(production.get("temporalFullFrameFallback", temporal.get("fullFrame", False)))
    planner_full = bool(planner.get("fullRepair", False))

    if planner_full:
        primary = (
            "production-full-full-frame-temporal-support"
            if temporal_full_frame or (full_work > 0.0 and temporal_work >= full_work - TOL)
            else "production-planner-selected-full"
        )
    elif candidate_bound > epsilon + TOL:
        primary = "candidate-certified-bound-over-epsilon"
    elif candidate_actual > epsilon + TOL:
        primary = "candidate-measured-error-over-epsilon"
    elif planner_work >= full_work - TOL:
        primary = "candidate-has-no-work-saving"
    else:
        primary = "local-eligible"

    terms = [
        {
            "name": "productionResolvedRgbBound",
            "value": resolved_bound,
            "fractionOfCandidateBound": ratio(resolved_bound, candidate_bound),
            "fractionOfEpsilon": ratio(resolved_bound, epsilon),
        },
        {
            "name": "postRepairResidualBound",
            "value": residual_bound,
            "fractionOfCandidateBound": ratio(residual_bound, candidate_bound),
            "fractionOfEpsilon": ratio(residual_bound, epsilon),
        },
    ]
    terms.sort(key=lambda item: float(item["value"]), reverse=True)

    return {
        "schemaVersion": 1,
        "artifact": "maveb-cbrc-case-decision-trace",
        "readOnly": True,
        "caseId": case_id,
        "dataset": row.get("dataset_id"),
        "sourceSceneId": row.get("source_scene_id"),
        "editFamily": row.get("edit_family", row.get("edit_class")),
        "couplingRegime": row.get("coupling_regime"),
        "decision": "FULL" if bool(row.get("fallback_full", False)) else "LOCAL",
        "primaryCause": primary,
        "epsilon": epsilon,
        "epsilon255": epsilon * 255.0,
        "candidate": {
            "bound": candidate_bound,
            "bound255": candidate_bound * 255.0,
            "actual": candidate_actual,
            "actual255": candidate_actual * 255.0,
            "boundOverEpsilon": ratio(candidate_bound, epsilon),
            "actualOverEpsilon": ratio(candidate_actual, epsilon),
            "certificateValid": candidate_actual <= candidate_bound + TOL,
        },
        "boundDecomposition": {
            "sumOfExposedTerms": resolved_bound + residual_bound,
            "matchesCandidateBound": abs((resolved_bound + residual_bound) - candidate_bound) <= 1e-10,
            "dominantTerm": terms[0]["name"] if terms else None,
            "terms": terms,
        },
        "sourceEdit": {
            "bound": source_bound,
            "actual": source_actual,
            "effectivity": ratio(source_bound, source_actual),
        },
        "productionPlanner": {
            "stable": planner.get("stable"),
            "passes": planner.get("passes"),
            "fullRepair": planner_full,
            "temporalRepairSelected": planner.get("temporalRepairSelected"),
            "temporalValidationStable": planner.get("temporalValidationStable"),
            "invalidationCoversCertifiedSupport": production.get("invalidationCoversCertifiedSupport"),
            "temporalFullFrameFallback": temporal_full_frame,
            "historyWeight": history_weight,
            "plannerWork": planner_work,
            "fullWork": full_work,
            "plannerWorkRatioFull": ratio(planner_work, full_work),
            "temporalRepairWork": temporal_work,
            "temporalRepairWorkRatioFull": ratio(temporal_work, full_work),
        },
        "locality": {
            "changedFraction": float(row.get("changed_fraction", 0.0)),
            "affectedPixelFraction": float(diagnostics.get("affectedPixelFraction", 0.0)),
            "hardClosureNodes": int(row.get("hard_closure_nodes", 0)),
            "candidateConeNodes": int(diagnostics.get("candidateConeNodes", 0)),
            "totalNodes": int(row.get("total_nodes", 0)),
            "candidateWork": float(diagnostics.get("candidateWork", row.get("planner_work", 0.0))),
            "fullWork": float(row.get("full_work", full_work)),
            "temporalPixelRatio": temporal.get("pixelRatio"),
            "publicationByteRatio": publication.get("byteRatio"),
        },
        "repair": {
            "mode": diagnostics.get("repairMode"),
            "residualScale": diagnostics.get("repairResidualScaleRequested"),
            "omittedGaussians": diagnostics.get("repairOmittedGaussians"),
            "appliedChangedGaussians": diagnostics.get("repairAppliedChangedGaussians"),
            "certificateViolationPixels": diagnostics.get("repairCertificateViolationPixels"),
        },
        "interpretation": (
            "The candidate bound is the production planner's resolved RGB bound plus "
            "the independent post-repair residual bound. A production FULL decision "
            "preempts LOCAL even when that arithmetic candidate would fit epsilon."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--case-id")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    row = choose_case(load_jsonl(args.rows.resolve()), args.case_id)
    case_id = str(row.get("case_id", ""))
    manifest_path = args.campaign_dir.resolve() / "cases" / case_id / "replay-manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"replay manifest not found: {manifest_path}")

    result = trace_case(row, load_json(manifest_path))
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
