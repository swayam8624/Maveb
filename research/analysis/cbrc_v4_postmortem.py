#!/usr/bin/env python3
"""Postmortem for reviewer-v4 locality results.

This analysis is intentionally read-only. It answers a narrow question that the
aggregate readiness report cannot: did support size, epsilon, or the non-zero
residual mode actually control the LOCAL/FULL decision?

It consumes the frozen v4 campaign plus completed case evidence. It never changes
the campaign, cases, epsilon values, residual scales, or planner outputs.
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
        raise ValueError("postmortem requires at least one campaign row")
    return rows


def label_residual(value: float) -> str:
    if abs(value) <= 1e-15:
        return "exact"
    denominator = round(1.0 / value) if value > 0.0 else 0
    return f"1/{denominator}" if denominator > 0 else f"{value:.9g}"


def summarize_group(records: list[dict[str, Any]]) -> dict[str, Any]:
    local = [record for record in records if bool(record["local"])]
    full = [record for record in records if bool(record["fallbackFull"])]
    candidate_ratios = [
        float(record["candidateBound"]) / float(record["epsilon"])
        for record in records
        if float(record["epsilon"]) > 0.0
    ]
    actual_ratios = [
        float(record["candidateActual"]) / float(record["epsilon"])
        for record in records
        if float(record["epsilon"]) > 0.0
    ]
    return {
        "cases": len(records),
        "localCases": len(local),
        "fullFallbackCases": len(full),
        "localRate": len(local) / len(records) if records else None,
        "nonzeroLocalCases": sum(bool(record["nonzeroLocal"]) for record in records),
        "medianCandidateBoundOverEpsilon": median(candidate_ratios)
        if candidate_ratios
        else None,
        "medianCandidateActualOverEpsilon": median(actual_ratios)
        if actual_ratios
        else None,
        "medianAffectedPixelFraction": median(
            [float(record["affectedPixelFraction"]) for record in records]
        ),
    }


def grouped_summary(
    records: list[dict[str, Any]],
    key,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(key(record))].append(record)
    return {
        name: summarize_group(values)
        for name, values in sorted(grouped.items())
    }


def decision_set(records: list[dict[str, Any]]) -> list[str]:
    values = {
        "FULL" if bool(record["fallbackFull"]) else "LOCAL"
        for record in records
    }
    return sorted(values)


def sensitivity(
    records: list[dict[str, Any]],
    *,
    fixed_key,
    varied_value,
) -> dict[str, Any]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[tuple(fixed_key(record))].append(record)

    sensitive: list[dict[str, Any]] = []
    invariant = 0
    for key, values in sorted(groups.items(), key=lambda item: str(item[0])):
        decisions = decision_set(values)
        values_seen = sorted(
            {
                str(varied_value(record))
                for record in values
            }
        )
        if len(decisions) > 1:
            sensitive.append(
                {
                    "fixedKey": list(key),
                    "variedValues": values_seen,
                    "decisions": decisions,
                    "cases": len(values),
                }
            )
        else:
            invariant += 1

    return {
        "groupCount": len(groups),
        "decisionSensitiveGroups": len(sensitive),
        "decisionInvariantGroups": invariant,
        "examples": sensitive[:12],
    }


def build(
    rows: list[dict[str, Any]],
    campaign: dict[str, Any],
    campaign_dir: Path,
) -> dict[str, Any]:
    metadata = evidence.case_metadata(campaign)
    records: list[dict[str, Any]] = []
    fallback_records: list[dict[str, Any]] = []

    for row in rows:
        case_id = str(row.get("case_id", ""))
        case = metadata.get(case_id)
        if case is None:
            raise ValueError(f"campaign metadata missing for case {case_id!r}")
        record = evidence.classify_row(
            row,
            case,
            zero_tol=evidence.DEFAULT_ZERO_TOL,
            near_boundary_ratio=evidence.DEFAULT_NEAR_BOUNDARY_RATIO,
        )
        records.append(record)
        fallback_records.append(
            fallback.classify_row(
                row,
                manifest=fallback.case_manifest(campaign_dir, case_id),
            )
        )

    causes = Counter(
        record["cause"]
        for record in fallback_records
        if bool(record["fallbackFull"])
    )
    manifest_resolved = sum(bool(record["manifestResolved"]) for record in fallback_records)

    by_residual = grouped_summary(
        records,
        lambda record: label_residual(float(record["repairResidualScale"])),
    )
    by_profile = grouped_summary(records, lambda record: record["severityProfile"])
    by_epsilon = grouped_summary(records, lambda record: f"{float(record['epsilon255']):g}/255")
    by_family = grouped_summary(records, lambda record: record["editFamily"])
    by_dataset = grouped_summary(records, lambda record: record["dataset"])

    # Locality sensitivity: hold dataset/edit/residual/epsilon fixed and change profile.
    profile_sensitivity = sensitivity(
        records,
        fixed_key=lambda record: (
            record["dataset"],
            record["sourceSceneId"],
            record["editFamily"],
            label_residual(float(record["repairResidualScale"])),
            float(record["epsilon255"]),
        ),
        varied_value=lambda record: record["severityProfile"],
    )

    # Residual sensitivity: hold dataset/edit/profile/epsilon fixed and change residual.
    residual_sensitivity = sensitivity(
        records,
        fixed_key=lambda record: (
            record["dataset"],
            record["sourceSceneId"],
            record["editFamily"],
            record["severityProfile"],
            float(record["epsilon255"]),
        ),
        varied_value=lambda record: label_residual(float(record["repairResidualScale"])),
    )

    # Epsilon sensitivity: exactly the crossover question.
    epsilon_sensitivity = sensitivity(
        records,
        fixed_key=lambda record: (
            record["dataset"],
            record["sourceSceneId"],
            record["editFamily"],
            record["severityProfile"],
            label_residual(float(record["repairResidualScale"])),
        ),
        varied_value=lambda record: f"{float(record['epsilon255']):g}/255",
    )

    exact_records = [
        record for record in records
        if abs(float(record["repairResidualScale"])) <= 1e-15
    ]
    residual_records = [
        record for record in records
        if float(record["repairResidualScale"]) > 0.0
    ]

    exact_all_local = bool(exact_records) and all(
        bool(record["local"]) for record in exact_records
    )
    residual_all_full = bool(residual_records) and all(
        bool(record["fallbackFull"]) for record in residual_records
    )

    fallback_by_cause: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in fallback_records:
        if record["fallbackFull"]:
            fallback_by_cause[str(record["cause"])].append(record)

    representative_causes = []
    for cause, values in sorted(fallback_by_cause.items()):
        values = sorted(
            values,
            key=lambda record: (
                -(float(record["candidateBound"]) / max(float(record["epsilon"]), 1e-30)),
                record["caseId"],
            ),
        )
        item = values[0]
        representative_causes.append(
            {
                "cause": cause,
                "cases": len(values),
                "caseId": item["caseId"],
                "dataset": item["dataset"],
                "editFamily": item["editFamily"],
                "candidateBoundOverEpsilon": (
                    float(item["candidateBound"]) / max(float(item["epsilon"]), 1e-30)
                ),
                "candidateActualOverEpsilon": (
                    float(item["candidateActual"]) / max(float(item["epsilon"]), 1e-30)
                ),
                "productionFullRepair": item["productionFullRepair"],
                "temporalFullFrameFallback": item["temporalFullFrameFallback"],
                "temporalRepairWorkRatioFull": item["temporalRepairWorkRatioFull"],
                "postRepairResidualBound": item["postRepairResidualBound"],
                "productionResolvedRgbBound": item["productionResolvedRgbBound"],
            }
        )

    conclusion = []
    if exact_all_local and residual_all_full:
        conclusion.append(
            "Decision is perfectly separated by residual mode: every exact-repair "
            "case is LOCAL and every non-zero residual case is FULL."
        )
    if profile_sensitivity["decisionSensitiveGroups"] == 0:
        conclusion.append(
            "Changing selected entity-size profile did not change a single binary "
            "LOCAL/FULL decision after dataset, edit, residual mode, and epsilon were held fixed."
        )
    if epsilon_sensitivity["decisionSensitiveGroups"] == 0:
        conclusion.append(
            "Changing epsilon across the frozen ladder did not change a single "
            "LOCAL/FULL decision within an otherwise identical stress key."
        )
    if residual_sensitivity["decisionSensitiveGroups"] > 0:
        conclusion.append(
            "Residual mode changes the decision under otherwise matched conditions; "
            "this isolates the current practical failure to the partial-repair/residual "
            "certificate or temporal-support path rather than edit locality alone."
        )

    return {
        "schemaVersion": 1,
        "artifact": "maveb-reviewer-v4-locality-postmortem",
        "protocol": campaign.get("protocol", campaign.get("campaignId")),
        "readOnly": True,
        "recordCount": len(records),
        "manifestResolvedCases": manifest_resolved,
        "byResidualScale": by_residual,
        "bySeverityProfile": by_profile,
        "byEpsilon": by_epsilon,
        "byEditFamily": by_family,
        "byDataset": by_dataset,
        "fallbackCauseCounts": dict(sorted(causes.items())),
        "profileDecisionSensitivity": profile_sensitivity,
        "residualDecisionSensitivity": residual_sensitivity,
        "epsilonDecisionSensitivity": epsilon_sensitivity,
        "exactRepairAllLocal": exact_all_local,
        "nonzeroResidualAllFull": residual_all_full,
        "representativeFallbackCauses": representative_causes,
        "conclusion": conclusion,
        "scientificBoundary": (
            "This is a post-hoc diagnostic of the frozen v4 execution. It may identify "
            "which already-frozen variable tracks the decision, but it must not be used "
            "to delete cases, retune epsilon, relabel outcomes, or rewrite v3/v4 evidence."
        ),
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Reviewer v4 locality postmortem",
        "",
        "This report is read-only and summarizes the already-frozen execution.",
        "",
        "## Main result",
        "",
    ]
    for item in report["conclusion"]:
        lines.append(f"- {item}")
    lines += ["", "## By residual scale", ""]
    for name, summary in report["byResidualScale"].items():
        lines.append(
            f"- **{name}**: {summary['localCases']} LOCAL / "
            f"{summary['fullFallbackCases']} FULL out of {summary['cases']}"
        )
    lines += ["", "## Decision sensitivity", ""]
    for title, key in (
        ("Support profile", "profileDecisionSensitivity"),
        ("Residual mode", "residualDecisionSensitivity"),
        ("Epsilon", "epsilonDecisionSensitivity"),
    ):
        value = report[key]
        lines.append(
            f"- **{title}**: {value['decisionSensitiveGroups']} sensitive / "
            f"{value['groupCount']} matched groups"
        )
    lines += ["", "## FULL causes", ""]
    for cause, count in report["fallbackCauseCounts"].items():
        lines.append(f"- **{cause}**: {count}")
    lines += [
        "",
        "## Scientific boundary",
        "",
        report["scientificBoundary"],
        "",
    ]
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
    json_path = output / "V4_LOCALITY_POSTMORTEM.json"
    md_path = output / "V4_LOCALITY_POSTMORTEM.md"
    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_markdown(report, md_path)

    print(json.dumps({
        "exactRepairAllLocal": report["exactRepairAllLocal"],
        "nonzeroResidualAllFull": report["nonzeroResidualAllFull"],
        "profileSensitiveGroups": report["profileDecisionSensitivity"]["decisionSensitiveGroups"],
        "residualSensitiveGroups": report["residualDecisionSensitivity"]["decisionSensitiveGroups"],
        "epsilonSensitiveGroups": report["epsilonDecisionSensitivity"]["decisionSensitiveGroups"],
        "fallbackCauseCounts": report["fallbackCauseCounts"],
        "report": str(json_path),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
