#!/usr/bin/env python3
"""Render and evaluate the prospectively frozen U6b Gaussian visibility confirmation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics

import numpy as np

from run_u5a_gaussian_depth import (
    paired_bootstrap_median,
    run_json,
    scene_summary,
    sha256_file,
    target_metrics,
)


STUDY_ID = "metric-uncertainty-u6b-opacity-visibility-confirmatory-v1"
PROTOCOL_SHA256 = "0c58590d7c71c24797d583bd2681c1fc8994028d9b188b1fbe5fb5a4c4e1b3e3"
ACQUISITION_SHA256 = "b0ce48a6c3cbf0ab8a037b5df7db80753aac0063ffba733d63ac5bf0b76ee5a9"
PREFLIGHT_SHA256 = "64fe0e95b0b2667b0141c6f3ec435116b725724e9b68b1be21cf05b225a39190"
RENDER_TOOL_SHA256 = "6b1f511633c259890b0f531ac414773a6a2bcbfcf5ee932585db036cfd4a997d"
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
BASELINE = METHODS[0]
CANDIDATE = METHODS[1]
SHUFFLED = METHODS[2]
TARGETS_PER_SCENE = 8
TOTAL_RENDERS = len(EXPECTED_SCENES) * len(METHODS) * TARGETS_PER_SCENE


def validate_protocol(path: Path) -> dict:
    if sha256_file(path) != PROTOCOL_SHA256:
        raise ValueError("U6b protocol SHA mismatch")
    protocol = json.loads(path.read_text())
    if (
        protocol.get("id") != STUDY_ID
        or protocol.get("status") != "preregistered-before-confirmatory-asset-acquisition"
        or not protocol.get("frozen")
    ):
        raise ValueError("U6b protocol is not the frozen confirmatory protocol")
    method_ids = tuple(item["id"] for item in protocol["methods"])
    if method_ids != METHODS:
        raise ValueError(f"U6b method order changed: {method_ids}")
    if int(protocol["targetViewSelection"]["count"]) != TARGETS_PER_SCENE:
        raise ValueError("U6b target count changed")
    return protocol


def validate_preparation(path: Path, protocol: dict) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    prep = json.loads(path.read_text())
    if (
        prep.get("study") != STUDY_ID
        or prep.get("status") != "prepared-no-u6b-render-or-metric-outcomes"
        or not prep.get("noRenderedDepthProduced")
        or not prep.get("noU6bMetricsProduced")
    ):
        raise ValueError("U6b preparation crossed the outcome boundary or has wrong status")
    if prep.get("protocolSha256") != PROTOCOL_SHA256:
        raise ValueError("U6b preparation protocol SHA mismatch")
    if prep.get("acquisitionLedgerSha256") != ACQUISITION_SHA256:
        raise ValueError("U6b preparation acquisition SHA mismatch")
    if prep.get("inputPreflightSha256") != PREFLIGHT_SHA256:
        raise ValueError("U6b preparation preflight SHA mismatch")
    if tuple(prep.get("methods", [])) != METHODS:
        raise ValueError("U6b preparation method order changed")
    scenes = [record["scene"] for record in prep.get("scenes", [])]
    if scenes != EXPECTED_SCENES:
        raise ValueError(f"U6b preparation scene order changed: {scenes}")
    if int(prep.get("pixelStride", -1)) != int(protocol["sourceGaussianSampling"]["pixelStride"]):
        raise ValueError("U6b preparation pixel stride changed")
    return prep


def validate_authorization(
    path: Path,
    *,
    preparation_sha: str,
    render_tool_sha: str,
) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    authorization = json.loads(path.read_text())
    if authorization.get("study") != STUDY_ID:
        raise ValueError("U6b authorization study mismatch")
    if authorization.get("stage") != "U6b-confirmatory-render-authorization":
        raise ValueError("U6b authorization stage mismatch")
    if authorization.get("status") != "authorized-after-frozen-preparation-before-render":
        raise ValueError("U6b render authorization status mismatch")
    if authorization.get("protocolSha256") != PROTOCOL_SHA256:
        raise ValueError("U6b authorization protocol SHA mismatch")
    if authorization.get("preparationSha256") != preparation_sha:
        raise ValueError("U6b authorization preparation SHA mismatch")
    if authorization.get("renderToolSha256") != render_tool_sha:
        raise ValueError("U6b authorization renderer SHA mismatch")
    if tuple(authorization.get("methods", [])) != METHODS:
        raise ValueError("U6b authorization method order mismatch")
    if int(authorization.get("sceneCount", -1)) != len(EXPECTED_SCENES):
        raise ValueError("U6b authorization scene count mismatch")
    if int(authorization.get("targetViewsPerScene", -1)) != TARGETS_PER_SCENE:
        raise ValueError("U6b authorization target count mismatch")
    if int(authorization.get("totalRenderCount", -1)) != TOTAL_RENDERS:
        raise ValueError("U6b authorization render count mismatch")
    if authorization.get("confirmatoryOutcomeObservedBeforeAuthorization") is not False:
        raise ValueError("U6b authorization does not certify an unopened outcome boundary")
    return authorization


def render_method(
    *,
    scene: str,
    method: str,
    prep_scene: dict,
    target_manifest_path: Path,
    targets: list[dict],
    output_root: Path,
    render_tool: Path,
) -> dict:
    method_prep = prep_scene["methods"][method]
    gaussian_path = Path(method_prep["gaussianPath"])
    if not gaussian_path.is_file() or sha256_file(gaussian_path) != method_prep["gaussianSha256"]:
        raise ValueError(f"U6b Gaussian SHA mismatch for {scene} {method}")
    if int(method_prep["primitiveCount"]) != int(prep_scene["primitiveCount"]):
        raise ValueError(f"U6b primitive count changed for {scene} {method}")
    if method != BASELINE and not method_prep.get("onlyOpacityChangedFromBaseline"):
        raise ValueError(f"U6b preparation did not certify opacity-only change for {scene} {method}")

    records: list[dict] = []
    for target in targets:
        target_index = int(target["targetIndex"])
        render_dir = output_root / "scenes" / scene / "renders" / method
        render_dir.mkdir(parents=True, exist_ok=True)
        rendered_path = render_dir / f"{target_index:02d}.f32"
        if rendered_path.exists():
            raise ValueError(f"U6b render already exists before immutable result: {rendered_path}")

        render_json = run_json(
            [
                str(render_tool),
                str(gaussian_path),
                str(target_manifest_path),
                "--target-index",
                str(target_index),
                "--output",
                str(rendered_path),
                "--json",
            ],
            label=f"U6b render {scene} {method} target {target_index}",
        )

        width = int(target["width"])
        height = int(target["height"])
        expected = width * height
        rendered = np.fromfile(rendered_path, dtype="<f4")
        faro_path = Path(target["faroDepthPath"])
        if not faro_path.is_file() or sha256_file(faro_path) != target["faroDepthSha256"]:
            raise ValueError(f"U6b FARO target SHA mismatch for {scene} target {target_index}")
        faro = np.fromfile(faro_path, dtype="<f4")
        if rendered.size != expected or faro.size != expected:
            raise ValueError(f"U6b rendered/FARO byte count mismatch for {scene} target {target_index}")

        metrics = target_metrics(
            rendered.reshape(height, width),
            faro.reshape(height, width),
        )
        records.append(
            {
                "targetIndex": target_index,
                "timestampNanoseconds": int(target["timestampNanoseconds"]),
                "renderSha256": sha256_file(rendered_path),
                "render": render_json,
                **metrics,
            }
        )
        print(
            json.dumps(
                {
                    "u6bMetric": {
                        "scene": scene,
                        "method": method,
                        "target": target_index,
                        "within5cm": metrics["within5cmFractionOfFaroValid"],
                        "coverage": metrics["coverageFraction"],
                        "maeMetres": metrics["absoluteDepthErrorMeanMetres"],
                    }
                },
                sort_keys=True,
            ),
            flush=True,
        )

    return {
        "gaussianSha256": method_prep["gaussianSha256"],
        "primitiveCount": int(method_prep["primitiveCount"]),
        "targets": records,
        "sceneSummary": scene_summary(records),
    }


def evaluate_gate(scene_results: dict[str, dict], protocol: dict) -> dict:
    evaluation = protocol["evaluation"]
    gate = evaluation["positiveConfirmatoryGate"]
    replicates = int(evaluation["pairedSceneBootstrapReplicates"])
    seed = int(evaluation["pairedSceneBootstrapSeed"])

    candidate_minus_baseline: list[float] = []
    candidate_minus_shuffled: list[float] = []
    coverage_ratios: list[float] = []
    candidate_better_baseline = 0
    candidate_better_shuffled = 0
    candidate_mae_not_worse = 0
    per_scene: dict[str, dict] = {}

    for scene in EXPECTED_SCENES:
        methods = scene_results[scene]["methods"]
        baseline = methods[BASELINE]["sceneSummary"]
        candidate = methods[CANDIDATE]["sceneSummary"]
        shuffled = methods[SHUFFLED]["sceneSummary"]

        baseline_primary = float(baseline["primaryWithin5cmFractionOfFaroValid"])
        candidate_primary = float(candidate["primaryWithin5cmFractionOfFaroValid"])
        shuffled_primary = float(shuffled["primaryWithin5cmFractionOfFaroValid"])
        delta_baseline = candidate_primary - baseline_primary
        delta_shuffled = candidate_primary - shuffled_primary
        candidate_minus_baseline.append(float(delta_baseline))
        candidate_minus_shuffled.append(float(delta_shuffled))
        candidate_better_baseline += int(delta_baseline > 0.0)
        candidate_better_shuffled += int(delta_shuffled > 0.0)

        baseline_coverage = float(baseline["coverageFractionMean"])
        candidate_coverage = float(candidate["coverageFractionMean"])
        if baseline_coverage <= 0.0:
            raise ValueError(f"U6b baseline coverage is non-positive for {scene}")
        coverage_ratio = candidate_coverage / baseline_coverage
        coverage_ratios.append(float(coverage_ratio))

        baseline_mae = baseline["absoluteDepthErrorMeanMetresAcrossTargetMeans"]
        candidate_mae = candidate["absoluteDepthErrorMeanMetresAcrossTargetMeans"]
        mae_not_worse = (
            baseline_mae is not None
            and candidate_mae is not None
            and float(candidate_mae) <= float(baseline_mae)
        )
        candidate_mae_not_worse += int(mae_not_worse)

        per_scene[scene] = {
            "candidateMinusBaseline": float(delta_baseline),
            "candidateMinusShuffled": float(delta_shuffled),
            "candidateToBaselineCoverageRatio": float(coverage_ratio),
            "candidateMeanAbsoluteDepthErrorNotWorseThanBaseline": bool(mae_not_worse),
        }

    bootstrap_baseline = paired_bootstrap_median(
        candidate_minus_baseline,
        replicates=replicates,
        seed=seed,
    )
    bootstrap_shuffled = paired_bootstrap_median(
        candidate_minus_shuffled,
        replicates=replicates,
        seed=seed,
    )
    median_coverage_ratio = float(statistics.median(coverage_ratios))
    minimum_coverage_ratio = float(min(coverage_ratios))

    baseline_gate = gate["candidateVsBaseline"]
    shuffled_gate = gate["candidateVsShuffled"]
    coverage_gate = gate["coverageGuard"]
    mae_gate = gate["overlapErrorGuard"]

    checks = {
        "candidateVsBaselineMedianEffectFloor": float(bootstrap_baseline["median"])
        >= float(baseline_gate["minimumMedianAbsolutePrimaryGain"]),
        "candidateVsBaselineWins": candidate_better_baseline
        >= int(baseline_gate["candidateMustBeatBaselineInAtLeastScenes"]),
        "candidateVsBaselinePaired95LowerAboveZero": bootstrap_baseline["lower95"] is not None
        and float(bootstrap_baseline["lower95"]) > 0.0,
        "candidateVsShuffledMedianEffectFloor": float(bootstrap_shuffled["median"])
        >= float(shuffled_gate["minimumMedianAbsolutePrimaryGain"]),
        "candidateVsShuffledWins": candidate_better_shuffled
        >= int(shuffled_gate["candidateMustBeatShuffledInAtLeastScenes"]),
        "candidateVsShuffledPaired95LowerAboveZero": bootstrap_shuffled["lower95"] is not None
        and float(bootstrap_shuffled["lower95"]) > 0.0,
        "coverageMedianRatio": median_coverage_ratio
        >= float(coverage_gate["minimumMedianCandidateToBaselineCoverageRatio"]),
        "coveragePerSceneMinimumRatio": minimum_coverage_ratio
        >= float(coverage_gate["minimumPerSceneCandidateToBaselineCoverageRatio"]),
        "overlapMeanAbsoluteErrorGuard": candidate_mae_not_worse
        >= int(mae_gate["candidateMeanAbsoluteDepthErrorMustNotExceedBaselineInAtLeastScenes"]),
    }

    return {
        "candidateMinusBaseline": bootstrap_baseline,
        "candidateMinusShuffled": bootstrap_shuffled,
        "candidateBetterThanBaselineSceneCount": candidate_better_baseline,
        "candidateBetterThanShuffledSceneCount": candidate_better_shuffled,
        "candidateMeanAbsoluteDepthErrorNotWorseSceneCount": candidate_mae_not_worse,
        "candidateToBaselineCoverageRatios": coverage_ratios,
        "medianCandidateToBaselineCoverageRatio": median_coverage_ratio,
        "minimumCandidateToBaselineCoverageRatio": minimum_coverage_ratio,
        "perScene": per_scene,
        "checks": checks,
        "allGateClausesPassed": all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--preparation", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--render-tool", type=Path, required=True)
    args = parser.parse_args()

    protocol = validate_protocol(args.protocol)
    preparation = validate_preparation(args.preparation, protocol)
    if not args.render_tool.is_file():
        raise FileNotFoundError(args.render_tool)
    render_tool_sha = sha256_file(args.render_tool)
    if render_tool_sha != RENDER_TOOL_SHA256:
        raise ValueError("U6b renderer binary SHA mismatch")
    authorization = validate_authorization(
        args.authorization,
        preparation_sha=sha256_file(args.preparation),
        render_tool_sha=render_tool_sha,
    )

    result_path = args.output_root / "result.json"
    if result_path.exists():
        raise ValueError("U6b result.json already exists; confirmatory outcome will not be overwritten")

    existing = list(args.output_root.glob("scenes/*/renders/*/*.f32"))
    if existing:
        raise ValueError("U6b render files already exist before first confirmatory result; freeze recovery state before retry")

    prep_by_scene = {record["scene"]: record for record in preparation["scenes"]}
    scene_results: dict[str, dict] = {}
    render_count = 0

    for scene in EXPECTED_SCENES:
        prep_scene = prep_by_scene[scene]
        target_manifest_path = Path(prep_scene["targetManifestPath"])
        if not target_manifest_path.is_file() or sha256_file(target_manifest_path) != prep_scene["targetManifestSha256"]:
            raise ValueError(f"U6b target manifest SHA mismatch for {scene}")
        target_manifest = json.loads(target_manifest_path.read_text())
        targets = target_manifest.get("targets", [])
        if len(targets) != TARGETS_PER_SCENE:
            raise ValueError(f"U6b target count differs from eight for {scene}")
        indices = [int(target["targetIndex"]) for target in targets]
        if indices != list(range(TARGETS_PER_SCENE)):
            raise ValueError(f"U6b target order changed for {scene}: {indices}")

        method_results: dict[str, dict] = {}
        for method in METHODS:
            method_results[method] = render_method(
                scene=scene,
                method=method,
                prep_scene=prep_scene,
                target_manifest_path=target_manifest_path,
                targets=targets,
                output_root=args.output_root,
                render_tool=args.render_tool,
            )
            render_count += TARGETS_PER_SCENE

        scene_results[scene] = {
            "targetManifestSha256": prep_scene["targetManifestSha256"],
            "methods": method_results,
        }

    if render_count != TOTAL_RENDERS:
        raise ValueError(f"U6b rendered {render_count} targets, expected {TOTAL_RENDERS}")

    gate = evaluate_gate(scene_results, protocol)
    passed = bool(gate["allGateClausesPassed"])
    status = "completed-confirmatory-gate-passed" if passed else "completed-confirmatory-gate-not-passed"
    claim_policy = protocol["claimPolicy"]["ifPassed" if passed else "ifFailed"]

    payload = {
        "schemaVersion": 1,
        "study": STUDY_ID,
        "stage": "U6b-confirmatory-heldout-faro-depth",
        "status": status,
        "claimType": protocol["claimType"],
        "protocolSha256": sha256_file(args.protocol),
        "preparationSha256": sha256_file(args.preparation),
        "authorizationSha256": sha256_file(args.authorization),
        "renderToolSha256": render_tool_sha,
        "renderCount": render_count,
        "methodOrder": list(METHODS),
        "scenes": scene_results,
        "confirmatoryGate": gate,
        "decisionRule": protocol["evaluation"]["decisionRule"],
        "claimPolicyApplied": claim_policy,
        "claimBoundary": "This is the single prospectively frozen U6b confirmatory result on the untouched five-room set. U6a remains exploratory; prior U3/U3b/U4a/U5a negatives remain unchanged regardless of this decision.",
    }
    result_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
