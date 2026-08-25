#!/usr/bin/env python3
"""Read-only post-hoc heterogeneity audit for the sealed negative/null U6b result."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from pathlib import Path


STUDY_ID = "metric-uncertainty-u6c-heterogeneity-audit-v1"
PARENT_STUDY_ID = "metric-uncertainty-u6b-opacity-visibility-confirmatory-v1"
PARENT_RESULT_SHA256 = "c361fda74d005c3d76c2d33b83626e5ef4039ee9fbce177d0b42e42fc9a0a823"
EXPECTED_SCENES = [
    "ca1m-42898811",
    "ca1m-45261121",
    "ca1m-47895341",
    "ca1m-47332915",
    "ca1m-47331971",
]
METHODS = (
    "depth-only-fixed-opacity",
    "calibrated-relative-precision-opacity",
    "shuffled-relative-precision-opacity",
)
BASELINE, CANDIDATE, SHUFFLED = METHODS


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_float(record: dict, key: str) -> float:
    value = record.get(key)
    if value is None:
        raise ValueError(f"U6c required metric is undefined: {key}")
    return float(value)


def indexed_targets(method_payload: dict) -> dict[int, dict]:
    targets = {int(record["targetIndex"]): record for record in method_payload.get("targets", [])}
    if sorted(targets) != list(range(8)):
        raise ValueError("U6c parent result target indices are not exactly 0..7")
    return targets


def method_summary(scene_payload: dict, method: str) -> dict:
    methods = scene_payload.get("methods")
    if not isinstance(methods, dict) or method not in methods:
        raise ValueError(f"U6c parent result is missing method: {method}")
    summary = methods[method].get("sceneSummary")
    if not isinstance(summary, dict):
        raise ValueError(f"U6c parent result is missing scene summary: {method}")
    return summary


def scene_audit(scene: str, scene_payload: dict, frozen_gate_scene: dict) -> dict:
    baseline = method_summary(scene_payload, BASELINE)
    candidate = method_summary(scene_payload, CANDIDATE)
    shuffled = method_summary(scene_payload, SHUFFLED)

    candidate_primary = require_float(candidate, "primaryWithin5cmFractionOfFaroValid")
    baseline_primary = require_float(baseline, "primaryWithin5cmFractionOfFaroValid")
    shuffled_primary = require_float(shuffled, "primaryWithin5cmFractionOfFaroValid")
    delta_baseline = candidate_primary - baseline_primary
    delta_shuffled = candidate_primary - shuffled_primary

    if abs(delta_baseline - float(frozen_gate_scene["candidateMinusBaseline"])) > 1.0e-12:
        raise ValueError(f"U6c frozen candidate-minus-baseline mismatch for {scene}")
    if abs(delta_shuffled - float(frozen_gate_scene["candidateMinusShuffled"])) > 1.0e-12:
        raise ValueError(f"U6c frozen candidate-minus-shuffled mismatch for {scene}")

    baseline_targets = indexed_targets(scene_payload["methods"][BASELINE])
    candidate_targets = indexed_targets(scene_payload["methods"][CANDIDATE])
    shuffled_targets = indexed_targets(scene_payload["methods"][SHUFFLED])

    target_deltas_baseline: list[float] = []
    target_deltas_shuffled: list[float] = []
    for target_index in range(8):
        candidate_value = require_float(
            candidate_targets[target_index], "within5cmFractionOfFaroValid"
        )
        baseline_value = require_float(
            baseline_targets[target_index], "within5cmFractionOfFaroValid"
        )
        shuffled_value = require_float(
            shuffled_targets[target_index], "within5cmFractionOfFaroValid"
        )
        target_deltas_baseline.append(candidate_value - baseline_value)
        target_deltas_shuffled.append(candidate_value - shuffled_value)

    baseline_coverage = require_float(baseline, "coverageFractionMean")
    candidate_coverage = require_float(candidate, "coverageFractionMean")
    shuffled_coverage = require_float(shuffled, "coverageFractionMean")
    baseline_mae = require_float(baseline, "absoluteDepthErrorMeanMetresAcrossTargetMeans")
    candidate_mae = require_float(candidate, "absoluteDepthErrorMeanMetresAcrossTargetMeans")
    shuffled_mae = require_float(shuffled, "absoluteDepthErrorMeanMetresAcrossTargetMeans")
    baseline_p95 = require_float(baseline, "absoluteDepthErrorP95MetresAcrossTargetP95")
    candidate_p95 = require_float(candidate, "absoluteDepthErrorP95MetresAcrossTargetP95")
    shuffled_p95 = require_float(shuffled, "absoluteDepthErrorP95MetresAcrossTargetP95")
    baseline_within10 = require_float(baseline, "within10cmFractionOfFaroValidMean")
    candidate_within10 = require_float(candidate, "within10cmFractionOfFaroValidMean")
    shuffled_within10 = require_float(shuffled, "within10cmFractionOfFaroValidMean")

    return {
        "scene": scene,
        "primaryWithin5cm": {
            "baseline": baseline_primary,
            "candidate": candidate_primary,
            "shuffled": shuffled_primary,
            "candidateMinusBaseline": delta_baseline,
            "candidateMinusShuffled": delta_shuffled,
        },
        "coverage": {
            "baseline": baseline_coverage,
            "candidate": candidate_coverage,
            "shuffled": shuffled_coverage,
            "candidateMinusBaseline": candidate_coverage - baseline_coverage,
            "candidateMinusShuffled": candidate_coverage - shuffled_coverage,
            "candidateToBaselineRatio": candidate_coverage / baseline_coverage,
        },
        "meanAbsoluteDepthErrorMetres": {
            "baseline": baseline_mae,
            "candidate": candidate_mae,
            "shuffled": shuffled_mae,
            "candidateMinusBaseline": candidate_mae - baseline_mae,
            "candidateMinusShuffled": candidate_mae - shuffled_mae,
        },
        "p95DepthErrorMetres": {
            "baseline": baseline_p95,
            "candidate": candidate_p95,
            "shuffled": shuffled_p95,
            "candidateMinusBaseline": candidate_p95 - baseline_p95,
            "candidateMinusShuffled": candidate_p95 - shuffled_p95,
        },
        "within10cmFraction": {
            "baseline": baseline_within10,
            "candidate": candidate_within10,
            "shuffled": shuffled_within10,
            "candidateMinusBaseline": candidate_within10 - baseline_within10,
            "candidateMinusShuffled": candidate_within10 - shuffled_within10,
        },
        "targetLevelPrimary": {
            "candidateMinusBaseline": target_deltas_baseline,
            "candidateMinusShuffled": target_deltas_shuffled,
            "candidateBetterThanBaselineTargetCount": sum(
                value > 0.0 for value in target_deltas_baseline
            ),
            "candidateBetterThanShuffledTargetCount": sum(
                value > 0.0 for value in target_deltas_shuffled
            ),
            "medianCandidateMinusBaseline": float(statistics.median(target_deltas_baseline)),
            "medianCandidateMinusShuffled": float(statistics.median(target_deltas_shuffled)),
        },
    }


def summarize_result(result: dict) -> dict:
    if result.get("study") != PARENT_STUDY_ID:
        raise ValueError("U6c parent result study mismatch")
    if result.get("status") != "completed-confirmatory-gate-not-passed":
        raise ValueError("U6c requires the sealed negative/null U6b result")
    if result.get("renderCount") != 120:
        raise ValueError("U6c parent render count mismatch")
    if tuple(result.get("methodOrder", [])) != METHODS:
        raise ValueError("U6c parent method order changed")
    gate = result.get("confirmatoryGate")
    if not isinstance(gate, dict) or gate.get("allGateClausesPassed") is not False:
        raise ValueError("U6c parent gate is not the frozen negative/null decision")
    frozen_per_scene = gate.get("perScene")
    if not isinstance(frozen_per_scene, dict):
        raise ValueError("U6c parent result is missing frozen per-scene gate records")
    result_scenes = result.get("scenes")
    if not isinstance(result_scenes, dict) or list(result_scenes) != EXPECTED_SCENES:
        raise ValueError("U6c parent result scene order changed")

    scene_records = [
        scene_audit(scene, result_scenes[scene], frozen_per_scene[scene])
        for scene in EXPECTED_SCENES
    ]
    deltas_baseline = [
        record["primaryWithin5cm"]["candidateMinusBaseline"] for record in scene_records
    ]
    deltas_shuffled = [
        record["primaryWithin5cm"]["candidateMinusShuffled"] for record in scene_records
    ]

    ranking_baseline = sorted(
        (
            {
                "scene": record["scene"],
                "candidateMinusBaseline": record["primaryWithin5cm"]["candidateMinusBaseline"],
            }
            for record in scene_records
        ),
        key=lambda record: record["candidateMinusBaseline"],
        reverse=True,
    )
    ranking_shuffled = sorted(
        (
            {
                "scene": record["scene"],
                "candidateMinusShuffled": record["primaryWithin5cm"]["candidateMinusShuffled"],
            }
            for record in scene_records
        ),
        key=lambda record: record["candidateMinusShuffled"],
        reverse=True,
    )

    return {
        "schemaVersion": 1,
        "study": STUDY_ID,
        "stage": "U6c-post-hoc-read-only-heterogeneity-audit",
        "status": "completed-post-hoc-descriptive-audit",
        "parentStudy": PARENT_STUDY_ID,
        "parentResultStatus": result["status"],
        "parentAllGateClausesPassed": False,
        "sceneCount": 5,
        "methodOrder": list(METHODS),
        "scenes": scene_records,
        "heterogeneity": {
            "candidateMinusBaselineSceneValues": deltas_baseline,
            "candidateMinusBaselineMedian": float(statistics.median(deltas_baseline)),
            "candidateMinusBaselineMinimum": float(min(deltas_baseline)),
            "candidateMinusBaselineMaximum": float(max(deltas_baseline)),
            "candidateMinusBaselineRange": float(max(deltas_baseline) - min(deltas_baseline)),
            "candidateMinusShuffledSceneValues": deltas_shuffled,
            "candidateMinusShuffledMedian": float(statistics.median(deltas_shuffled)),
            "candidateMinusShuffledMinimum": float(min(deltas_shuffled)),
            "candidateMinusShuffledMaximum": float(max(deltas_shuffled)),
            "candidateMinusShuffledRange": float(max(deltas_shuffled) - min(deltas_shuffled)),
            "rankingByCandidateMinusBaseline": ranking_baseline,
            "rankingByCandidateMinusShuffled": ranking_shuffled,
        },
        "integrity": {
            "sourceWasFrozenU6bResultOnly": True,
            "renderFilesRead": False,
            "rerendered": False,
            "faroMetricsRecomputedFromDepth": False,
            "confirmatoryGateRecomputed": False,
            "bootstrapRecomputed": False,
            "transferRuleFitOrTuned": False,
            "roomsDroppedReplacedOrReweighted": False,
        },
        "claimBoundary": (
            "This audit is descriptive and post hoc. It explains heterogeneity in the already-sealed "
            "negative/null U6b result and cannot change that decision or justify tuning on these rooms."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--u6b-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.output.exists():
        raise ValueError("U6c audit output already exists; it will not be overwritten")
    if not args.protocol.is_file() or not args.u6b_result.is_file():
        raise FileNotFoundError("U6c protocol or parent U6b result is missing")

    protocol = json.loads(args.protocol.read_text())
    if protocol.get("id") != STUDY_ID or protocol.get("frozen") is not True:
        raise ValueError("U6c protocol is not the frozen post-hoc audit scope")
    if protocol.get("parentResultSha256") != PARENT_RESULT_SHA256:
        raise ValueError("U6c protocol parent result SHA changed")
    actual_result_sha = sha256_file(args.u6b_result)
    if actual_result_sha != PARENT_RESULT_SHA256:
        raise ValueError("U6c parent U6b result SHA mismatch")

    result = json.loads(args.u6b_result.read_text())
    payload = summarize_result(result)
    payload["protocolSha256"] = sha256_file(args.protocol)
    payload["parentResultSha256"] = actual_result_sha

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
