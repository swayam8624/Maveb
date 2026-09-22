#!/usr/bin/env python3
"""Audit whether a CBRC experiment bundle has the evidence expected before paper writing.

This is deliberately not an acceptance predictor. It checks reproducibility and
evidence completeness only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


EMPIRICAL_SAFETY_GROUND_TRUTH = (
    "independent candidate full-reference residual <= epsilon"
)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def audit(
    campaign_dir: Path,
    calibration: Path,
    sparse_summary: Path,
    empirical: Path,
    visual_package: Path,
    visual_quality: Path | None = None,
    trained_status: Path | None = None,
    ablation_stress: Path | None = None,
) -> dict[str, Any]:
    campaign_rows = rows(campaign_dir / "campaign-rows.jsonl")
    gates = load(campaign_dir / "campaign-gates.json")
    evaluation = load(campaign_dir / "campaign-evaluation.json")
    calibration_data = load(calibration)
    sparse = load(sparse_summary)
    empirical_data = load(empirical)
    visuals = load(visual_package)
    timings_path = campaign_dir / "campaign-timings.jsonl"
    timing_rows = rows(timings_path) if timings_path.is_file() else []

    scenes = {str(row.get("scene_id", "")) for row in campaign_rows}
    units = {str(row.get("work_cost_unit", "")) for row in campaign_rows}
    model_versions = {str(row.get("work_cost_model_version", "")) for row in campaign_rows}
    local = sum(not bool(row.get("fallback_full", False)) for row in campaign_rows)
    full = sum(bool(row.get("fallback_full", False)) for row in campaign_rows)
    violations = []
    source_effect_evidence_cases = 0
    nontrivial_source_effect_cases = 0
    for row in campaign_rows:
        row_qois = row.get("qois", {})
        for qoi_name, qoi in row_qois.items():
            actual = float(qoi["measured_full_reference_error"])
            bound = float(qoi["certified_bound"])
            epsilon = float(qoi["epsilon"])
            if actual > bound + 1e-12 or bound > epsilon + 1e-12:
                violations.append(
                    {
                        "case_id": row.get("case_id"),
                        "qoi": qoi_name,
                        "actual": actual,
                        "bound": bound,
                        "epsilon": epsilon,
                    }
                )

        rgb_qoi = row_qois.get("rgb_linf")
        source_actual = row.get("candidateDiagnostics", {}).get(
            "sourceEditActualRgbError"
        )
        if rgb_qoi is not None and source_actual is not None:
            source_actual = float(source_actual)
            source_epsilon = float(rgb_qoi["epsilon"])
            source_effect_evidence_cases += 1
            if source_actual > source_epsilon + 1e-12:
                nontrivial_source_effect_cases += 1

    required_domains = {
        "gaussiansInspected",
        "gaussiansUpdated",
        "gpuPublicationBytes",
        "temporalPixelsInvalidated",
    }
    calibration_domains = set(calibration_data.get("domains", {}))
    visual_assets = visuals.get("assets", {})
    visual_files = [
        visual_package.parent / str(relative)
        for relative in visual_assets.values()
    ]

    checks = {
        "campaignAtLeast50FrozenCases": len(campaign_rows) >= 50,
        "campaignAtLeast4Scenes": len(scenes) >= 4,
        "campaignGatePass": bool(gates.get("pass", False)),
        "strictEvaluationPass": bool(evaluation.get("pass", False)),
        "zeroCertificateViolations": not violations,
        "sourceEditOracleEvidencePresent": (
            source_effect_evidence_cases == len(campaign_rows)
        ),
        "majorityEditsHaveVisibleSourceEffect": (
            nontrivial_source_effect_cases >= max(1, len(campaign_rows) // 2)
        ),
        "hasCertifiedLocalCases": local > 0,
        "hasAutomaticFullFallbacks": full > 0,
        "millisecondCostModelBound": units == {"ms"},
        "singleFrozenCostModelVersion": len(model_versions) == 1 and "" not in model_versions,
        "calibrationCoversAllLedgerDomains": required_domains <= calibration_domains,
        "sparseSelectionExact": bool(sparse.get("exactSelectionAgreement", False)),
        "sparseDiscoveryActuallyReducesInspections": float(
            sparse.get("minimumInspectionRatio", 1.0)
        ) < 1.0,
        "heldoutEmpiricalProtocolPresent": int(empirical_data.get("heldoutCases", 0)) > 0,
        "heldoutEmpiricalReportsSafety": "heldoutUnsafeFalseLocalRate" in empirical_data,
        "heldoutEmpiricalUsesIndependentResidual": (
            empirical_data.get("safetyGroundTruth")
            == EMPIRICAL_SAFETY_GROUND_TRUTH
        ),
        "measuredPhaseTimingsPresent": len(timing_rows) == len(campaign_rows),
        "siggraphVisualPackagePresent": bool(visual_assets)
        and all(path.is_file() for path in visual_files),
    }

    visual_quality_status = None
    if visual_quality is not None and visual_quality.is_file():
        visual_quality_status = load(visual_quality)
        visual_aggregate = visual_quality_status.get("aggregate", {})
        checks["visualQualityAuditPresent"] = (
            visual_quality_status.get("artifact")
            == "maveb-cbrc-visual-quality-audit"
        )
        checks["visualQualityCoversCampaign"] = int(
            visual_aggregate.get("case_count", -1)
        ) == len(campaign_rows)
        checks["visualQualityCoversScenes"] = int(
            visual_aggregate.get("scene_count", -1)
        ) >= len(scenes)
        checks["visualQualityShowsNontrivialEdits"] = int(
            visual_aggregate.get("cases_with_visible_pixel_change", 0)
        ) >= max(1, len(campaign_rows) // 2)

    trained = None
    if trained_status is not None and trained_status.is_file():
        trained = load(trained_status)
        checks["trained3dgsValidationPass"] = bool(trained.get("pass", False))

    stress = None
    if ablation_stress is not None and ablation_stress.is_file():
        stress = load(ablation_stress)
        checks["ablationMechanismStressPass"] = (
            bool(stress.get("pass", False))
            and int(stress.get("separatedMechanisms", 0))
            == int(stress.get("mechanismCount", -1))
            and bool(stress.get("syntheticMechanismIsolationOnly", False))
        )

    core_ready = all(checks.values()) if trained_status is not None else all(
        value for key, value in checks.items() if key != "trained3dgsValidationPass"
    )
    return {
        "schemaVersion": 2,
        "artifact": "maveb-cbrc-paper-readiness-audit",
        "paperAcceptancePrediction": None,
        "paperAcceptancePredictionNote": (
            "This audit does not predict venue acceptance. It only checks the frozen "
            "implementation/evidence/visualization package requested by the project."
        ),
        "rows": len(campaign_rows),
        "scenes": len(scenes),
        "localCases": local,
        "fullFallbackCases": full,
        "certificateViolations": violations,
        "sourceEffectEvidenceCases": source_effect_evidence_cases,
        "nontrivialSourceEffectCases": nontrivial_source_effect_cases,
        "nontrivialSourceEffectRate": (
            0.0
            if not campaign_rows
            else nontrivial_source_effect_cases / len(campaign_rows)
        ),
        "workCostUnits": sorted(units),
        "workCostModelVersions": sorted(model_versions),
        "checks": checks,
        "corePaperEvidenceReady": core_ready,
        "visualQualityStatus": visual_quality_status,
        "trained3dgsStatus": trained,
        "ablationStressStatus": stress,
        "interpretationBoundary": (
            "A calibrated heterogeneous cost model is an isolated hardware-derived work estimate. "
            "Measured campaign phase wall times are reported separately. Neither quantity should "
            "be relabeled as end-to-end speedup without a paired end-to-end timing experiment."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--sparse-summary", type=Path, required=True)
    parser.add_argument("--empirical", type=Path, required=True)
    parser.add_argument("--visual-package", type=Path, required=True)
    parser.add_argument("--trained-status", type=Path)
    parser.add_argument("--ablation-stress", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(
        args.campaign_dir,
        args.calibration,
        args.sparse_summary,
        args.empirical,
        args.visual_package,
        args.visual_quality,
        args.trained_status,
        args.ablation_stress,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["corePaperEvidenceReady"] else 5


if __name__ == "__main__":
    raise SystemExit(main())
