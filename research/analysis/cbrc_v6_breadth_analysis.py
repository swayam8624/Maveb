#!/usr/bin/env python3
"""Scene-clustered confirmatory analysis for MAVEB reviewer-v6 breadth.

v6 repeats the frozen v5 mechanism protocol on five deterministically selected
scenes per dataset. Parameter sweeps within a scene are correlated by design, so
the primary summaries and bootstrap intervals operate on scene-level aggregates.
Pooled case counts are retained only as secondary descriptive evidence.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ANALYSIS_DIR = ROOT / "research" / "analysis"
if str(ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(ANALYSIS_DIR))

import cbrc_reviewer_evidence_v3 as evidence
import cbrc_v5_certificate_analysis as v5audit


BOOTSTRAP_SEED = 1904
BOOTSTRAP_REPLICATES = 10_000


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
        raise ValueError(f"no JSONL rows: {path}")
    return rows


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def safe_rate(numerator: int, denominator: int) -> float | None:
    return None if denominator <= 0 else numerator / denominator


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lo = int(math.floor(position))
    hi = int(math.ceil(position))
    if lo == hi:
        return ordered[lo]
    weight = position - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def scene_bootstrap_mean(
    values: list[float],
    *,
    replicates: int = BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    if not values:
        return {"scenes": 0, "mean": None, "ci95": [None, None]}
    rng = random.Random(seed)
    n = len(values)
    samples: list[float] = []
    for _ in range(replicates):
        samples.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    return {
        "scenes": n,
        "mean": sum(values) / n,
        "ci95": [percentile(samples, 0.025), percentile(samples, 0.975)],
        "replicates": replicates,
        "seed": seed,
    }


def stratified_scene_bootstrap_mean(
    rows: list[dict[str, Any]],
    value_key: str,
    *,
    replicates: int = BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Bootstrap scenes within each fixed dataset stratum.

    v6 has exactly five scenes from each frozen v5 dataset family. Resampling
    within dataset preserves that design in every bootstrap replicate and avoids
    allowing a replicate to be dominated by one dataset family.
    """
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        value = row.get(value_key)
        if value is None:
            continue
        grouped[str(row["dataset"])].append(float(value))
    if not grouped:
        return {
            "scenes": 0,
            "datasets": 0,
            "mean": None,
            "ci95": [None, None],
        }
    dataset_sizes = {dataset: len(values) for dataset, values in grouped.items()}
    if any(size <= 0 for size in dataset_sizes.values()):
        raise ValueError("stratified scene bootstrap encountered an empty dataset stratum")

    flattened = [value for values in grouped.values() for value in values]
    rng = random.Random(seed)
    samples: list[float] = []
    for _ in range(replicates):
        draw: list[float] = []
        for dataset in sorted(grouped):
            values = grouped[dataset]
            n = len(values)
            draw.extend(values[rng.randrange(n)] for _ in range(n))
        samples.append(sum(draw) / len(draw))

    return {
        "scenes": len(flattened),
        "datasets": len(grouped),
        "scenesPerDataset": dict(sorted(dataset_sizes.items())),
        "mean": sum(flattened) / len(flattened),
        "ci95": [percentile(samples, 0.025), percentile(samples, 0.975)],
        "replicates": replicates,
        "seed": seed,
        "resampling": "within-dataset-scene-bootstrap",
    }


def scene_key(record: dict[str, Any]) -> tuple[str, str]:
    return str(record["dataset"]), str(record["sourceSceneId"])


def build_scene_metrics(
    records: list[dict[str, Any]],
    crossover_groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[scene_key(record)].append(record)

    crossovers: Counter[tuple[str, str]] = Counter()
    for group in crossover_groups:
        if str(group.get("editFamily")) != "opacity":
            continue
        crossovers[(str(group.get("dataset")), str(group.get("sourceSceneId")))] += 1

    result: list[dict[str, Any]] = []
    for (dataset, scene), values in sorted(grouped.items()):
        opacity = [item for item in values if item["editFamily"] == "opacity"]
        translation = [item for item in values if item["editFamily"] == "translation"]
        opacity_nonzero = [
            item for item in opacity if float(item["repairResidualScale"]) > 0.0
        ]
        translation_nonzero = [
            item for item in translation if float(item["repairResidualScale"]) > 0.0
        ]
        opacity_nonzero_local = [item for item in opacity_nonzero if item["nonzeroLocal"]]
        translation_nonzero_local = [
            item for item in translation_nonzero if item["nonzeroLocal"]
        ]
        opacity_stress = {
            item["stressKey"] for item in opacity_nonzero
        }

        effectivity = []
        legacy_to_delta_ratios = []
        counterfactual_covered = []
        delta_eligible = []
        legacy_eligible = []
        rescued_by_delta = []
        for item in opacity_nonzero:
            actual = float(item["postRepairActualRgbError"])
            bound = float(item["postRepairResidualBound"])
            if actual > 1e-15:
                effectivity.append(bound / actual)

            covered = bool(item.get("repairLegacyEnvelopeCounterfactualComputed", False))
            counterfactual_covered.append(covered)
            if covered:
                legacy_bound = float(item.get("repairLegacyEnvelopeBound", 0.0))
                if bound > 0.0:
                    legacy_to_delta_ratios.append(legacy_bound / bound)
                epsilon = float(item["epsilon"])
                production = float(item["productionResolvedRgbBound"])
                delta_ok = production + bound <= epsilon + 1e-12
                legacy_ok = production + legacy_bound <= epsilon + 1e-12
                delta_eligible.append(delta_ok)
                legacy_eligible.append(legacy_ok)
                rescued_by_delta.append(delta_ok and not legacy_ok)

        local_work = [
            float(item["workRatioFull"])
            for item in opacity_nonzero_local
            if item.get("workRatioFull") is not None
        ]
        local_actual_to_epsilon = [
            float(item["actualToEpsilon"])
            for item in opacity_nonzero_local
            if item.get("actualToEpsilon") is not None
        ]
        opacity_rate = safe_rate(len(opacity_nonzero_local), len(opacity_nonzero))
        translation_rate = safe_rate(
            len(translation_nonzero_local),
            len(translation_nonzero),
        )
        delta = (
            None
            if opacity_rate is None or translation_rate is None
            else opacity_rate - translation_rate
        )

        result.append(
            {
                "dataset": dataset,
                "scene": scene,
                "cases": len(values),
                "opacityCases": len(opacity),
                "translationCases": len(translation),
                "opacityNonzeroResidualCases": len(opacity_nonzero),
                "translationNonzeroResidualCases": len(translation_nonzero),
                "opacityNonzeroLocalCases": len(opacity_nonzero_local),
                "translationNonzeroLocalCases": len(translation_nonzero_local),
                "opacityNonzeroLocalRate": opacity_rate,
                "translationNonzeroLocalRate": translation_rate,
                "pairedNonzeroLocalRateDelta": delta,
                "opacityCrossoverStressKeys": crossovers[(dataset, scene)],
                "opacityEligibleStressKeys": len(opacity_stress),
                "opacityCrossoverFraction": safe_rate(
                    crossovers[(dataset, scene)],
                    len(opacity_stress),
                ),
                "medianOpacityResidualEffectivity": median(effectivity),
                "maximumOpacityLocalActualToEpsilon": (
                    max(local_actual_to_epsilon) if local_actual_to_epsilon else None
                ),
                "medianOpacityLocalActualToEpsilon": median(local_actual_to_epsilon),
                "opacityNearBoundaryLocalCases": sum(
                    bool(item["nearBoundaryLocal"]) for item in opacity_nonzero_local
                ),
                "medianLegacyToDeltaResidualBoundRatio": median(legacy_to_delta_ratios),
                "legacyCounterfactualCoveredCases": sum(counterfactual_covered),
                "legacyCounterfactualExpectedCases": len(opacity_nonzero),
                "deltaCertificateEligibleCases": sum(delta_eligible),
                "legacyEnvelopeEligibleCases": sum(legacy_eligible),
                "casesRescuedByDeltaCertificate": sum(rescued_by_delta),
                "deltaCertificateRescueRate": safe_rate(
                    sum(rescued_by_delta),
                    len(rescued_by_delta),
                ),
                "medianOpacityNonzeroLocalWorkRatioFull": median(local_work),
                "certificateViolations": sum(
                    not bool(item["certificateOk"]) for item in values
                ),
                "repairCertificateViolationCases": sum(
                    int(item["repairCertificateViolationPixels"]) > 0
                    for item in values
                ),
            }
        )
    return result


def load_baselines(path: Path) -> list[dict[str, Any]]:
    return load_jsonl(path)


def baseline_scene_metrics(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_scene_method: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        scene = str(row.get("scene_id", ""))
        dataset = str(row.get("dataset_id", scene.split("::", 1)[0] if "::" in scene else ""))
        for family in ("baselines", "ablations"):
            methods = row.get(family, {})
            if not isinstance(methods, dict):
                continue
            for method, payload in methods.items():
                if not isinstance(payload, dict):
                    continue
                by_scene_method[(scene, f"{family}:{method}")].append(
                    {
                        "dataset": dataset,
                        "passes": bool(payload.get("passes", False)),
                        "usedFullRebuild": bool(payload.get("usedFullRebuild", False)),
                        "workRatioFull": payload.get("workRatioFull"),
                    }
                )

    table: list[dict[str, Any]] = []
    for (scene, method), values in sorted(by_scene_method.items()):
        ratios = [
            float(item["workRatioFull"])
            for item in values
            if item["workRatioFull"] is not None
        ]
        table.append(
            {
                "scene": scene,
                "dataset": values[0]["dataset"] if values else "",
                "method": method,
                "cases": len(values),
                "passRate": sum(item["passes"] for item in values) / len(values),
                "fullRebuildRate": (
                    sum(item["usedFullRebuild"] for item in values) / len(values)
                ),
                "medianWorkRatioFull": median(ratios),
            }
        )

    by_method: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in table:
        by_method[row["method"]].append(row)

    summary: dict[str, Any] = {}
    for method, values in sorted(by_method.items()):
        work = [
            float(item["medianWorkRatioFull"])
            for item in values
            if item["medianWorkRatioFull"] is not None
        ]
        summary[method] = {
            "scenes": len(values),
            "meanScenePassRate": sum(float(item["passRate"]) for item in values) / len(values),
            "medianSceneWorkRatioFull": median(work),
            "meanSceneFullRebuildRate": (
                sum(float(item["fullRebuildRate"]) for item in values) / len(values)
            ),
        }
    return table, summary


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build(
    rows: list[dict[str, Any]],
    campaign: dict[str, Any],
    campaign_dir: Path,
    baseline_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    generic, records = evidence.analyze(rows, campaign)
    certificate = v5audit.build(rows, campaign, campaign_dir)
    scenes = build_scene_metrics(records, generic["crossoverGroups"])
    baseline_table, baseline_summary = baseline_scene_metrics(baseline_rows)

    datasets = sorted({item["dataset"] for item in scenes})
    scene_counts = Counter(item["dataset"] for item in scenes)
    opacity_positive_scenes = [
        item for item in scenes if int(item["opacityNonzeroLocalCases"]) > 0
    ]
    crossover_scenes = [
        item for item in scenes if int(item["opacityCrossoverStressKeys"]) > 0
    ]
    rescued_scenes = [
        item for item in scenes if int(item["casesRescuedByDeltaCertificate"]) > 0
    ]
    counterfactual_complete = all(
        int(item["legacyCounterfactualCoveredCases"])
        == int(item["legacyCounterfactualExpectedCases"])
        for item in scenes
    )
    positive_datasets = sorted({item["dataset"] for item in opacity_positive_scenes})

    legacy_to_delta = [
        float(item["medianLegacyToDeltaResidualBoundRatio"])
        for item in scenes
        if item["medianLegacyToDeltaResidualBoundRatio"] is not None
    ]
    scene_effectivity = [
        float(item["medianOpacityResidualEffectivity"])
        for item in scenes
        if item["medianOpacityResidualEffectivity"] is not None
    ]
    scene_boundary = [
        float(item["maximumOpacityLocalActualToEpsilon"])
        for item in scenes
        if item["maximumOpacityLocalActualToEpsilon"] is not None
    ]

    paired_bootstrap = stratified_scene_bootstrap_mean(
        scenes,
        "pairedNonzeroLocalRateDelta",
    )
    opacity_bootstrap = stratified_scene_bootstrap_mean(
        scenes,
        "opacityNonzeroLocalRate",
    )
    crossover_bootstrap = stratified_scene_bootstrap_mean(
        scenes,
        "opacityCrossoverFraction",
    )

    required_scene_count = 5 * len(datasets)
    minimum_positive_scenes = math.ceil(0.50 * len(scenes))
    minimum_positive_datasets = math.ceil(0.75 * len(datasets))
    lower_delta = paired_bootstrap["ci95"][0]

    gates = {
        "exactlyFiveScenesPerDataset": bool(datasets)
        and all(scene_counts[dataset] == 5 for dataset in datasets)
        and len(scenes) == required_scene_count,
        "certificateExperimentValid": bool(certificate["certificateExperimentValid"]),
        "noCertificateViolations": generic["certificateViolationCount"] == 0,
        "noRepairCertificateViolations": generic["repairCertificateViolationCount"] == 0,
        "sameOpacityLegacyCounterfactualCoverageComplete": counterfactual_complete,
        "deltaCertificateRescuesCasesInAtLeastHalfOfScenes": (
            len(rescued_scenes) >= minimum_positive_scenes
        ),
        "opacityGeneralizesToAtLeastHalfOfScenes": (
            len(opacity_positive_scenes) >= minimum_positive_scenes
        ),
        "opacityGeneralizesAcrossThreeQuartersOfDatasets": (
            len(positive_datasets) >= minimum_positive_datasets
        ),
        "sceneClusteredOpacityAdvantageLowerCIAboveZero": (
            lower_delta is not None and float(lower_delta) > 0.0
        ),
    }

    return {
        "schemaVersion": 1,
        "artifact": "maveb-cbrc-v6-confirmatory-breadth-audit",
        "protocol": campaign.get("protocol", campaign.get("campaignId")),
        "primaryUnitOfAnalysis": "scene",
        "sceneCount": len(scenes),
        "datasetCount": len(datasets),
        "sceneCountsByDataset": dict(sorted(scene_counts.items())),
        "pooledCaseCount": len(records),
        "certificateAudit": {
            "certificateExperimentValid": certificate["certificateExperimentValid"],
            "validityGates": certificate["validityGates"],
            "modeByEditFamily": certificate["modeByEditFamily"],
        },
        "sceneClustered": {
            "opacityNonzeroLocalRate": opacity_bootstrap,
            "translationNonzeroLocalRate": stratified_scene_bootstrap_mean(
                scenes,
                "translationNonzeroLocalRate",
            ),
            "pairedOpacityMinusTranslationNonzeroLocalRate": paired_bootstrap,
            "opacityCrossoverFraction": crossover_bootstrap,
            "sameOpacityLegacyEnvelopeAblation": {
                "counterfactualCoverageComplete": counterfactual_complete,
                "deltaCertificateRescueRate": stratified_scene_bootstrap_mean(
                    scenes,
                    "deltaCertificateRescueRate",
                ),
                "medianSceneLegacyToDeltaResidualBoundRatio": median(legacy_to_delta),
                "scenesWithAtLeastOneRescuedCase": len(rescued_scenes),
            },
            "certificateTightness": {
                "medianOfSceneMedianResidualEffectivity": median(scene_effectivity),
                "medianOfSceneMaximumActualToEpsilon": median(scene_boundary),
                "maximumSceneMaximumActualToEpsilon": (
                    max(scene_boundary) if scene_boundary else None
                ),
                "pooledNearBoundaryLocalCases": generic["nearBoundaryLocalCases"],
            },
            "scenesWithNonzeroOpacityLocal": len(opacity_positive_scenes),
            "scenesWithOpacityCrossover": len(crossover_scenes),
            "datasetsWithNonzeroOpacityLocal": positive_datasets,
        },
        "confirmatoryGates": gates,
        "confirmatoryPass": all(gates.values()),
        "sceneMetrics": scenes,
        "baselineSceneSummary": baseline_summary,
        "pooledReviewerAudit": {
            "reviewerEvidenceReady": generic["reviewerEvidenceReady"],
            "certifiedNonzeroLocalCases": generic["certifiedNonzeroLocalCases"],
            "toleranceCrossoverGroups": generic["toleranceCrossoverGroups"],
            "nearBoundaryLocalCases": generic["nearBoundaryLocalCases"],
            "nonzeroLocalDatasets": generic["nonzeroLocalDatasets"],
        },
        "scientificBoundary": (
            "The v6 primary evidence is scene-clustered. Repeated epsilon, residual, profile, "
            "and edit-family cases from the same scene are not treated as independent samples. "
            "Confidence intervals resample scenes within each frozen dataset family so every "
            "bootstrap replicate preserves the 5x4 stratified design. The protocol repeats "
            "v5 without algorithm or threshold changes."
        ),
        "_baselineSceneRows": baseline_table,
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    ci = report["sceneClustered"]["pairedOpacityMinusTranslationNonzeroLocalRate"]["ci95"]
    lines = [
        "# MAVEB v6 confirmatory breadth audit",
        "",
        f"- Confirmatory pass: **{report['confirmatoryPass']}**",
        f"- Independent scenes: **{report['sceneCount']}**",
        f"- Datasets: **{report['datasetCount']}**",
        f"- Pooled parameter cases (secondary): **{report['pooledCaseCount']}**",
        "",
        "## Frozen confirmatory gates",
        "",
    ]
    for name, passed in report["confirmatoryGates"].items():
        lines.append(f"- {'PASS' if passed else 'OPEN'} — {name}")
    lines += [
        "",
        "## Scene-clustered primary endpoint",
        "",
        (
            "- Mean per-scene non-zero LOCAL-rate advantage "
            f"(opacity minus translation): "
            f"**{report['sceneClustered']['pairedOpacityMinusTranslationNonzeroLocalRate']['mean']}**"
        ),
        f"- Deterministic scene-bootstrap 95% CI: **[{ci[0]}, {ci[1]}]**",
        (
            "- Scenes with at least one certified non-zero opacity LOCAL repair: "
            f"**{report['sceneClustered']['scenesWithNonzeroOpacityLocal']}**"
        ),
        (
            "- Scenes with at least one opacity tolerance crossover: "
            f"**{report['sceneClustered']['scenesWithOpacityCrossover']}**"
        ),
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
    parser.add_argument("--baselines", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    campaign = load_json(args.campaign.resolve())
    rows = load_jsonl(args.rows.resolve())
    baseline_rows = load_baselines(args.baselines.resolve())
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    report = build(rows, campaign, args.campaign_dir.resolve(), baseline_rows)
    baseline_rows_out = report.pop("_baselineSceneRows")

    json_path = output / "V6_BREADTH_AUDIT.json"
    md_path = output / "V6_BREADTH_AUDIT.md"
    scene_csv = output / "V6_SCENE_METRICS.csv"
    baseline_csv = output / "V6_BASELINE_SCENE_METRICS.csv"
    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_markdown(report, md_path)
    write_csv(scene_csv, report["sceneMetrics"])
    write_csv(baseline_csv, baseline_rows_out)

    print(
        json.dumps(
            {
                "confirmatoryPass": report["confirmatoryPass"],
                "confirmatoryGates": report["confirmatoryGates"],
                "sceneCount": report["sceneCount"],
                "sceneClustered": report["sceneClustered"],
                "report": str(json_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
