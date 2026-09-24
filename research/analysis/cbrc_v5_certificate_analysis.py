#!/usr/bin/env python3
"""Audit the frozen reviewer-v5 opacity-delta certificate experiment.

The audit separates certificate validity from favorable planner outcomes. A v5
run is methodologically valid when its frozen cases execute without certificate
violations, the intended certificate modes are routed correctly, and the new
opacity residual bound is monotone under matched residual-amplitude sweeps.
LOCAL cases and epsilon crossovers are outcomes, not pass criteria.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ANALYSIS_DIR = ROOT / "research" / "analysis"
if str(ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(ANALYSIS_DIR))

import cbrc_reviewer_evidence_v3 as evidence
import cbrc_reviewer_fallback_diagnostics as fallback


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
        raise ValueError("v5 certificate audit requires at least one row")
    return rows


def label_residual(value: float) -> str:
    if abs(value) <= 1e-15:
        return "exact"
    denominator = round(1.0 / value)
    return f"1/{denominator}"


def build(
    rows: list[dict[str, Any]],
    campaign: dict[str, Any],
    campaign_dir: Path,
) -> dict[str, Any]:
    generic, records = evidence.analyze(rows, campaign)
    metadata = evidence.case_metadata(campaign)

    raw_by_id = {str(row.get("case_id", "")): row for row in rows}
    mode_counts: Counter[str] = Counter()
    mode_by_family: dict[str, Counter[str]] = defaultdict(Counter)
    mode_routing_errors: list[dict[str, Any]] = []

    for record in records:
        mode = str(record["repairCertificateMode"])
        family = str(record["editFamily"])
        residual = float(record["repairResidualScale"])
        mode_counts[mode] += 1
        mode_by_family[family][mode] += 1
        expected = (
            "exact-zero-v1"
            if residual == 0.0
            else (
                "opacity-delta-lipschitz-v1"
                if family == "opacity"
                else "opacity-envelope-union-v1"
            )
        )
        if mode != expected:
            mode_routing_errors.append(
                {
                    "caseId": record["caseId"],
                    "editFamily": family,
                    "residualScale": residual,
                    "expected": expected,
                    "observed": mode,
                }
            )

    # Hold scene/profile/family/epsilon fixed and inspect only residual amplitude.
    series: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        key = (
            record["dataset"],
            record["sourceSceneId"],
            record["severityProfile"],
            record["editFamily"],
            float(record["epsilon255"]),
        )
        series[key].append(record)

    monotonicity_violations: list[dict[str, Any]] = []
    opacity_series = 0
    opacity_positive_series = 0
    for key, values in sorted(series.items(), key=lambda item: str(item[0])):
        values.sort(key=lambda item: float(item["repairResidualScale"]))
        if key[3] != "opacity":
            continue
        opacity_series += 1
        positive = [
            item for item in values if float(item["repairResidualScale"]) > 0.0
        ]
        if len(positive) >= 2:
            opacity_positive_series += 1
        previous: dict[str, Any] | None = None
        for item in values:
            if previous is not None:
                current_scale = float(item["repairResidualScale"])
                previous_scale = float(previous["repairResidualScale"])
                current_bound = float(item["postRepairResidualBound"])
                previous_bound = float(previous["postRepairResidualBound"])
                if (
                    current_scale > previous_scale
                    and current_bound + TOL < previous_bound
                ):
                    monotonicity_violations.append(
                        {
                            "fixedKey": list(key),
                            "fromScale": previous_scale,
                            "toScale": current_scale,
                            "fromBound": previous_bound,
                            "toBound": current_bound,
                            "fromCaseId": previous["caseId"],
                            "toCaseId": item["caseId"],
                        }
                    )
            previous = item

    opacity_nonzero = [
        record
        for record in records
        if record["editFamily"] == "opacity"
        and float(record["repairResidualScale"]) > 0.0
    ]
    translation_nonzero = [
        record
        for record in records
        if record["editFamily"] == "translation"
        and float(record["repairResidualScale"]) > 0.0
    ]

    def effectivities(items: list[dict[str, Any]]) -> list[float]:
        result: list[float] = []
        for item in items:
            actual = float(item["postRepairActualRgbError"])
            bound = float(item["postRepairResidualBound"])
            if actual > 1e-15:
                result.append(bound / actual)
        return result

    opacity_effectivity = effectivities(opacity_nonzero)
    translation_effectivity = effectivities(translation_nonzero)

    fallback_records = [
        fallback.classify_row(
            raw_by_id[case_id],
            manifest=fallback.case_manifest(campaign_dir, case_id),
        )
        for case_id in metadata
        if case_id in raw_by_id
    ]
    fallback_causes = Counter(
        str(item["cause"])
        for item in fallback_records
        if bool(item["fallbackFull"])
    )

    by_family: dict[str, dict[str, Any]] = {}
    for family in sorted({str(record["editFamily"]) for record in records}):
        subset = [record for record in records if record["editFamily"] == family]
        by_family[family] = {
            "cases": len(subset),
            "localCases": sum(bool(item["local"]) for item in subset),
            "fullFallbackCases": sum(bool(item["fallbackFull"]) for item in subset),
            "nonzeroLocalCases": sum(bool(item["nonzeroLocal"]) for item in subset),
            "crossoverStressKeys": sum(
                item["editFamily"] == family
                for item in generic["crossoverGroups"]
            ),
            "certificateModes": dict(sorted(mode_by_family[family].items())),
        }

    validity_gates = {
        "noSelectedCertificateViolations": generic["certificateViolationCount"] == 0,
        "noRepairCertificateViolations": generic["repairCertificateViolationCount"] == 0,
        "certificateModeRoutingCorrect": not mode_routing_errors,
        "opacityResidualBoundMonotone": not monotonicity_violations
        and opacity_positive_series > 0,
    }

    outcome_summary = {
        "certifiedNonzeroLocalCases": generic["certifiedNonzeroLocalCases"],
        "nearBoundaryLocalCases": generic["nearBoundaryLocalCases"],
        "toleranceCrossoverGroups": generic["toleranceCrossoverGroups"],
        "nonzeroLocalDatasets": generic["nonzeroLocalDatasets"],
        "reviewerEvidenceReadyUnderLegacyGates": generic["reviewerEvidenceReady"],
    }

    return {
        "schemaVersion": 1,
        "artifact": "maveb-cbrc-reviewer-opacity-delta-v5-audit",
        "protocol": campaign.get("protocol", campaign.get("campaignId")),
        "readOnly": True,
        "recordCount": len(records),
        "validityGates": validity_gates,
        "certificateExperimentValid": all(validity_gates.values()),
        "modeCounts": dict(sorted(mode_counts.items())),
        "modeByEditFamily": {
            family: dict(sorted(counts.items()))
            for family, counts in sorted(mode_by_family.items())
        },
        "modeRoutingErrors": mode_routing_errors,
        "opacityMatchedResidualSeries": opacity_series,
        "opacityPositiveResidualSeries": opacity_positive_series,
        "monotonicityViolations": monotonicity_violations,
        "opacityResidualEffectivity": {
            "definedCases": len(opacity_effectivity),
            "median": median(opacity_effectivity) if opacity_effectivity else None,
            "minimum": min(opacity_effectivity) if opacity_effectivity else None,
            "maximum": max(opacity_effectivity) if opacity_effectivity else None,
        },
        "translationResidualEffectivity": {
            "definedCases": len(translation_effectivity),
            "median": median(translation_effectivity)
            if translation_effectivity
            else None,
            "minimum": min(translation_effectivity)
            if translation_effectivity
            else None,
            "maximum": max(translation_effectivity)
            if translation_effectivity
            else None,
        },
        "byEditFamily": by_family,
        "fallbackCauseCounts": dict(sorted(fallback_causes.items())),
        "outcomes": outcome_summary,
        "genericReviewerAudit": {
            key: generic[key]
            for key in (
                "localCases",
                "fullFallbackCases",
                "certificateViolationCount",
                "repairCertificateViolationCount",
                "certifiedPartialRepairCases",
                "certifiedNonzeroLocalCases",
                "nearBoundaryLocalCases",
                "toleranceCrossoverGroups",
                "nonzeroLocalDatasets",
                "reviewerEvidenceReady",
            )
        },
        "scientificBoundary": (
            "The validity gates test the new certificate and routing, not whether it "
            "produces LOCAL outcomes. Favorable LOCAL/crossover evidence is reported "
            "separately and cannot be manufactured by deleting or retuning frozen cases."
        ),
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Reviewer v5 opacity-delta certificate audit",
        "",
        f"Certificate experiment valid: **{report['certificateExperimentValid']}**",
        "",
        "## Validity gates",
        "",
    ]
    for name, passed in report["validityGates"].items():
        lines.append(f"- {'PASS' if passed else 'OPEN'} — {name}")
    lines += ["", "## Outcomes", ""]
    for name, value in report["outcomes"].items():
        lines.append(f"- {name}: **{value}**")
    lines += ["", "## Edit families", ""]
    for family, item in report["byEditFamily"].items():
        lines.append(
            f"- **{family}**: {item['localCases']} LOCAL / "
            f"{item['fullFallbackCases']} FULL; "
            f"{item['nonzeroLocalCases']} non-zero LOCAL; "
            f"{item['crossoverStressKeys']} crossover keys"
        )
    lines += ["", "## Certificate modes", ""]
    for mode, count in report["modeCounts"].items():
        lines.append(f"- {mode}: {count}")
    lines += ["", "## Scientific boundary", "", report["scientificBoundary"], ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    campaign = load_json(args.campaign.resolve())
    rows = load_jsonl(args.rows.resolve())
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    report = build(rows, campaign, args.campaign_dir.resolve())
    json_path = output / "V5_CERTIFICATE_AUDIT.json"
    md_path = output / "V5_CERTIFICATE_AUDIT.md"
    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_markdown(report, md_path)
    print(
        json.dumps(
            {
                "certificateExperimentValid": report["certificateExperimentValid"],
                "validityGates": report["validityGates"],
                "outcomes": report["outcomes"],
                "byEditFamily": report["byEditFamily"],
                "report": str(json_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
