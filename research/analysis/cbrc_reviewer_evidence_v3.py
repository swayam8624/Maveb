#!/usr/bin/env python3
"""Analyze reviewer-targeted CBRC evidence.

This report is descriptive and fail-closed. It does not change campaign
validity. It answers four practical-review questions:
  1. Do certified LOCAL repairs ever have measurable non-zero FULL-reference error?
  2. Does the same physical edit exhibit a FULL->LOCAL crossover as epsilon changes?
  3. How tight are the certified bounds when measured error is non-zero?
  4. Are there real captured-scene examples suitable for publication visuals?
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


DYNAMIC_DATASETS = {"bonn-rgbd-dynamic", "3rscan"}
DEFAULT_ZERO_TOL = 1e-12
DEFAULT_NEAR_BOUNDARY_RATIO = 0.25


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def case_metadata(campaign: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(case["id"]): case
        for case in campaign.get("cases", [])
        if isinstance(case, dict) and case.get("id")
    }


def safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator <= 0.0 or not math.isfinite(denominator):
        return None
    return numerator / denominator


def classify_row(
    row: dict[str, Any],
    case: dict[str, Any],
    *,
    zero_tol: float,
    near_boundary_ratio: float,
) -> dict[str, Any]:
    qoi = row["qois"]["rgb_linf"]
    epsilon = float(qoi["epsilon"])
    bound = float(qoi["certified_bound"])
    actual = float(qoi["measured_full_reference_error"])
    fallback = bool(row.get("fallback_full", False))
    diagnostics = row.get("candidateDiagnostics", {})
    candidate_actual = float(diagnostics.get("candidateActualRgbError", actual))
    candidate_bound = float(diagnostics.get("candidateRgbBound", bound))
    repair_mode = str(
        diagnostics.get("repairMode", "exact-changed-support-v1")
    )
    repair_omit_fraction = float(
        diagnostics.get("repairOmitFractionRequested", 0.0)
    )
    repair_residual_scale = float(
        diagnostics.get("repairResidualScaleRequested", 0.0)
    )
    repair_omitted_gaussians = int(
        diagnostics.get("repairOmittedGaussians", 0)
    )
    repair_applied_gaussians = int(
        diagnostics.get("repairAppliedChangedGaussians", 0)
    )
    repair_certificate_violations = int(
        diagnostics.get("repairCertificateViolationPixels", 0)
    )
    matrix = case.get("matrix_tags", {}) if isinstance(case, dict) else {}

    certificate_ok = actual <= bound + 1e-12 and bound <= epsilon + 1e-12
    candidate_certificate_ok = candidate_actual <= candidate_bound + 1e-12
    local = not fallback
    nonzero_local = local and actual > zero_tol
    actual_to_epsilon = safe_ratio(actual, epsilon)
    bound_to_epsilon = safe_ratio(bound, epsilon)
    effectivity = None if actual <= zero_tol else safe_ratio(bound, actual)
    near_boundary = bool(
        nonzero_local
        and actual_to_epsilon is not None
        and actual_to_epsilon >= near_boundary_ratio
    )

    dataset = str(
        row.get(
            "dataset_id",
            case.get("dataset_id", matrix.get("dataset_id", "unknown")),
        )
    )
    source_scene = str(
        row.get(
            "source_scene_id",
            case.get(
                "source_scene_id",
                matrix.get("source_scene_id", row.get("scene_id", "unknown")),
            ),
        )
    )
    family = str(
        row.get(
            "edit_family",
            case.get("edit_family", matrix.get("edit_family", "unknown")),
        )
    )
    profile = str(matrix.get("severity_profile", "unknown"))
    stress_key = str(
        matrix.get(
            "stress_key",
            f"{dataset}::{source_scene}::{profile}::{family}",
        )
    )
    epsilon_255 = float(matrix.get("epsilon_255", epsilon * 255.0))

    return {
        "caseId": str(row.get("case_id", case.get("id", ""))),
        "stressKey": stress_key,
        "sceneId": str(row.get("scene_id", case.get("scene_id", "unknown"))),
        "dataset": dataset,
        "sourceSceneId": source_scene,
        "representation": str(
            row.get("representation", case.get("representation", "unknown"))
        ),
        "editFamily": family,
        "severityProfile": profile,
        "couplingRegime": str(
            row.get("coupling_regime", case.get("coupling_regime", "unknown"))
        ),
        "epsilon": epsilon,
        "epsilon255": epsilon_255,
        "fallbackFull": fallback,
        "local": local,
        "certificateOk": certificate_ok,
        "candidateCertificateOk": candidate_certificate_ok,
        "actual": actual,
        "bound": bound,
        "candidateActual": candidate_actual,
        "candidateBound": candidate_bound,
        "actualToEpsilon": actual_to_epsilon,
        "boundToEpsilon": bound_to_epsilon,
        "effectivity": effectivity,
        "nonzeroLocal": nonzero_local,
        "nearBoundaryLocal": near_boundary,
        "workRatioFull": safe_ratio(
            float(row.get("planner_work", 0.0)),
            float(row.get("full_work", 0.0)),
        ),
        "affectedPixelFraction": float(
            diagnostics.get("affectedPixelFraction", 0.0)
        ),
        "repairMode": repair_mode,
        "repairOmitFraction": repair_omit_fraction,
        "repairResidualScale": repair_residual_scale,
        "repairOmittedGaussians": repair_omitted_gaussians,
        "repairAppliedChangedGaussians": repair_applied_gaussians,
        "repairCertificateViolationPixels": repair_certificate_violations,
        "naturalChangePair": matrix.get(
            "natural_change_pair",
            matrix.get("naturalChangePair"),
        ),
    }


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return 0.5 * (ordered[middle - 1] + ordered[middle])


def analyze(
    rows: list[dict[str, Any]],
    campaign: dict[str, Any],
    *,
    zero_tol: float = DEFAULT_ZERO_TOL,
    near_boundary_ratio: float = DEFAULT_NEAR_BOUNDARY_RATIO,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if zero_tol < 0:
        raise ValueError("zero_tol must be non-negative")
    if not 0.0 <= near_boundary_ratio <= 1.0:
        raise ValueError("near_boundary_ratio must be in [0,1]")

    metadata = case_metadata(campaign)
    records: list[dict[str, Any]] = []
    for row in rows:
        case_id = str(row.get("case_id", ""))
        case = metadata.get(case_id)
        if case is None:
            raise ValueError(f"campaign metadata missing for case {case_id!r}")
        records.append(
            classify_row(
                row,
                case,
                zero_tol=zero_tol,
                near_boundary_ratio=near_boundary_ratio,
            )
        )

    if not records:
        raise ValueError("reviewer evidence analysis requires at least one row")

    certificate_violations = [
        record for record in records if not record["certificateOk"]
    ]
    local = [record for record in records if record["local"]]
    full = [record for record in records if record["fallbackFull"]]
    nonzero = [record for record in local if record["nonzeroLocal"]]
    near = [record for record in local if record["nearBoundaryLocal"]]

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[record["stressKey"]].append(record)

    crossover_groups: list[dict[str, Any]] = []
    for key, values in sorted(groups.items()):
        ordered = sorted(values, key=lambda item: item["epsilon"])
        decisions = ["LOCAL" if item["local"] else "FULL" for item in ordered]
        has_local = any(item["local"] for item in ordered)
        has_full = any(item["fallbackFull"] for item in ordered)
        if has_local and has_full:
            local_eps = [item["epsilon255"] for item in ordered if item["local"]]
            full_eps = [
                item["epsilon255"] for item in ordered if item["fallbackFull"]
            ]
            crossover_groups.append(
                {
                    "stressKey": key,
                    "dataset": ordered[0]["dataset"],
                    "sourceSceneId": ordered[0]["sourceSceneId"],
                    "editFamily": ordered[0]["editFamily"],
                    "severityProfile": ordered[0]["severityProfile"],
                    "repairResidualScale": ordered[0]["repairResidualScale"],
                    "epsilon255": [item["epsilon255"] for item in ordered],
                    "decisions": decisions,
                    "maximumFullEpsilon255": max(full_eps),
                    "minimumLocalEpsilon255": min(local_eps),
                    "localNonzeroCases": sum(
                        bool(item["nonzeroLocal"]) for item in ordered
                    ),
                }
            )

    datasets_nonzero = sorted({record["dataset"] for record in nonzero})
    dynamic_candidates = [
        record
        for record in nonzero
        if record["dataset"] in DYNAMIC_DATASETS
    ]
    natural_change_candidates = [
        record
        for record in nonzero
        if record.get("naturalChangePair")
        or record["dataset"] == "bonn-rgbd-dynamic"
    ]
    effectivities = [
        float(record["effectivity"])
        for record in nonzero
        if record["effectivity"] is not None
    ]

    nonzero_ranked = sorted(
        nonzero,
        key=lambda record: (
            -(record["actualToEpsilon"] or 0.0),
            record["effectivity"]
            if record["effectivity"] is not None
            else float("inf"),
            record["workRatioFull"]
            if record["workRatioFull"] is not None
            else float("inf"),
            record["caseId"],
        ),
    )
    dynamic_ranked = sorted(
        dynamic_candidates,
        key=lambda record: (
            -(record["actualToEpsilon"] or 0.0),
            -(record["affectedPixelFraction"] or 0.0),
            record["effectivity"]
            if record["effectivity"] is not None
            else float("inf"),
            record["caseId"],
        ),
    )

    repair_certificate_violations = [
        record
        for record in records
        if int(record["repairCertificateViolationPixels"]) > 0
    ]
    partial_mode_records = [
        record
        for record in records
        if (
            (
                record["repairMode"] == "certified-omitted-gaussians-v1"
                and record["repairOmittedGaussians"] > 0
            )
            or (
                record["repairMode"] == "certified-graded-residual-v1"
                and record["repairResidualScale"] > 0.0
            )
        )
    ]

    readiness_gates = {
        "noCertificateViolations": not certificate_violations,
        "noRepairCertificateViolations": not repair_certificate_violations,
        "hasCertifiedPartialRepairMode": bool(partial_mode_records),
        "hasCertifiedNonzeroLocal": bool(nonzero),
        "hasToleranceCrossover": bool(crossover_groups),
        "nonzeroAcrossAtLeastTwoDatasets": len(datasets_nonzero) >= 2,
        "hasDynamicCapturedSceneCandidate": bool(dynamic_candidates),
        "hasCapturedChangeContext": bool(natural_change_candidates),
    }

    report = {
        "schemaVersion": 1,
        "artifact": "maveb-cbrc-reviewer-evidence-audit",
        "protocol": campaign.get("protocol", campaign.get("campaignId")),
        "recordCount": len(records),
        "localCases": len(local),
        "fullFallbackCases": len(full),
        "certificateViolationCount": len(certificate_violations),
        "repairCertificateViolationCount": len(repair_certificate_violations),
        "certifiedPartialRepairCases": len(partial_mode_records),
        "certifiedNonzeroLocalCases": len(nonzero),
        "nearBoundaryLocalCases": len(near),
        "nonzeroLocalDatasets": datasets_nonzero,
        "dynamicCapturedSceneCandidates": len(dynamic_candidates),
        "capturedChangeContextCandidates": len(natural_change_candidates),
        "toleranceCrossoverGroups": len(crossover_groups),
        "zeroTolerance": zero_tol,
        "nearBoundaryRatioThreshold": near_boundary_ratio,
        "effectivityDefinedCount": len(effectivities),
        "minimumEffectivity": min(effectivities) if effectivities else None,
        "medianEffectivity": median(effectivities),
        "readinessGates": readiness_gates,
        "reviewerEvidenceReady": all(readiness_gates.values()),
        "topCertifiedNonzeroCases": nonzero_ranked[:12],
        "topDynamicVisualCandidates": dynamic_ranked[:8],
        "crossoverGroups": crossover_groups,
        "byDataset": {
            dataset: {
                "cases": sum(record["dataset"] == dataset for record in records),
                "localCases": sum(
                    record["dataset"] == dataset and record["local"]
                    for record in records
                ),
                "fullFallbackCases": sum(
                    record["dataset"] == dataset and record["fallbackFull"]
                    for record in records
                ),
                "certifiedNonzeroLocalCases": sum(
                    record["dataset"] == dataset and record["nonzeroLocal"]
                    for record in records
                ),
                "nearBoundaryLocalCases": sum(
                    record["dataset"] == dataset
                    and record["nearBoundaryLocal"]
                    for record in records
                ),
            }
            for dataset in sorted({record["dataset"] for record in records})
        },
        "byEditFamily": {
            family: {
                "cases": sum(record["editFamily"] == family for record in records),
                "localCases": sum(
                    record["editFamily"] == family and record["local"]
                    for record in records
                ),
                "fullFallbackCases": sum(
                    record["editFamily"] == family and record["fallbackFull"]
                    for record in records
                ),
                "certifiedNonzeroLocalCases": sum(
                    record["editFamily"] == family and record["nonzeroLocal"]
                    for record in records
                ),
            }
            for family in sorted({record["editFamily"] for record in records})
        },
        "interpretation": (
            "reviewerEvidenceReady is a manuscript-evidence readiness check, not a "
            "certificate-validity gate. A false readiness item must be reported rather "
            "than repaired by deleting cases or retuning the frozen protocol. Scientific "
            "validity remains actual<=bound<=epsilon for each LOCAL result; FULL outcomes "
            "remain evidence."
        ),
        "records": records,
    }
    return report, records


def write_csv(records: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "caseId",
        "stressKey",
        "dataset",
        "sourceSceneId",
        "representation",
        "editFamily",
        "severityProfile",
        "couplingRegime",
        "epsilon255",
        "fallbackFull",
        "actual",
        "bound",
        "candidateActual",
        "candidateBound",
        "actualToEpsilon",
        "boundToEpsilon",
        "effectivity",
        "nonzeroLocal",
        "nearBoundaryLocal",
        "workRatioFull",
        "affectedPixelFraction",
        "repairMode",
        "repairOmitFraction",
        "repairResidualScale",
        "repairOmittedGaussians",
        "repairAppliedChangedGaussians",
        "repairCertificateViolationPixels",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field) for field in fields})


def write_markdown(report: dict[str, Any], path: Path) -> None:
    gates = report["readinessGates"]
    lines = [
        "# MAVEB reviewer-targeted evidence audit",
        "",
        f"- Records: **{report['recordCount']}**",
        f"- LOCAL: **{report['localCases']}**",
        f"- FULL fallback: **{report['fullFallbackCases']}**",
        f"- Certified non-zero LOCAL: **{report['certifiedNonzeroLocalCases']}**",
        f"- Near-boundary LOCAL: **{report['nearBoundaryLocalCases']}**",
        f"- Tolerance crossover groups: **{report['toleranceCrossoverGroups']}**",
        f"- Non-zero LOCAL datasets: **{', '.join(report['nonzeroLocalDatasets']) or 'none'}**",
        "",
        "## Reviewer-readiness checks",
        "",
    ]
    for name, passed in gates.items():
        lines.append(f"- {'PASS' if passed else 'OPEN'} - {name}")
    lines.extend(
        [
            "",
            "These checks answer the practical graphics-review objections. They do not "
            "replace the core safety contract actual <= bound <= epsilon, and an OPEN "
            "item must not be hidden by dropping or retuning frozen cases.",
            "",
            "## Strongest certified non-zero LOCAL examples",
            "",
        ]
    )
    for record in report["topCertifiedNonzeroCases"][:8]:
        ratio = record["actualToEpsilon"]
        effectivity = record["effectivity"]
        lines.append(
            f"- {record['caseId']} - {record['dataset']} / "
            f"{record['editFamily']} / eps={record['epsilon255']:.2f}/255; "
            f"actual/eps={(ratio or 0.0):.3f}; "
            f"bound/actual={effectivity if effectivity is not None else 'undefined'}; "
            f"work/FULL={record['workRatioFull']}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--zero-tol", type=float, default=DEFAULT_ZERO_TOL)
    parser.add_argument(
        "--near-boundary-ratio",
        type=float,
        default=DEFAULT_NEAR_BOUNDARY_RATIO,
    )
    args = parser.parse_args()

    campaign = load_json(args.campaign.resolve())
    rows = load_jsonl(args.rows.resolve())
    report, records = analyze(
        rows,
        campaign,
        zero_tol=args.zero_tol,
        near_boundary_ratio=args.near_boundary_ratio,
    )

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "REVIEWER_EVIDENCE_AUDIT.json"
    csv_path = output / "REVIEWER_EVIDENCE_AUDIT.csv"
    md_path = output / "REVIEWER_EVIDENCE_AUDIT.md"
    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_csv(records, csv_path)
    write_markdown(report, md_path)

    print(
        json.dumps(
            {
                "reviewerEvidenceReady": report["reviewerEvidenceReady"],
                "certifiedNonzeroLocalCases": report["certifiedNonzeroLocalCases"],
                "nearBoundaryLocalCases": report["nearBoundaryLocalCases"],
                "toleranceCrossoverGroups": report["toleranceCrossoverGroups"],
                "nonzeroLocalDatasets": report["nonzeroLocalDatasets"],
                "dynamicCapturedSceneCandidates": report[
                    "dynamicCapturedSceneCandidates"
                ],
                "capturedChangeContextCandidates": report[
                    "capturedChangeContextCandidates"
                ],
                "report": str(json_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
