#!/usr/bin/env python3
"""Render and evaluate frozen U5a uncertainty-shaped Gaussian surfels on held-out FARO depth."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import subprocess
import sys

import numpy as np


STUDY_ID = "metric-uncertainty-u5a-gaussian-depth-v1"
TARGET_CLARIFICATION_ID = "metric-uncertainty-u5a-target-camera-clarification-v1"
EVAL_CLARIFICATION_ID = "metric-uncertainty-u5a-evaluation-clarification-v1"
METHODS = (
    "depth-only-covariance",
    "calibrated-covariance",
    "shuffled-calibrated-covariance",
)
EXPECTED_SCENES = [
    "ca1m-48458481",
    "ca1m-48018737",
    "ca1m-45261587",
    "ca1m-42897538",
    "ca1m-48018375",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_json(command: list[str], *, label: str) -> dict:
    print(json.dumps({"u5aProgress": {"label": label, "command": command}}), file=sys.stderr, flush=True)
    completed = subprocess.run(command, text=True, capture_output=True)
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="", flush=True)
    if completed.returncode != 0:
        raise RuntimeError(f"{label} failed with exit code {completed.returncode}: {completed.stdout.strip()}")
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"{label} produced no JSON output")
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} did not end in JSON: {lines[-1]}") from exc


def nearest_tie_lower(values: list[float], fraction: float) -> float | None:
    finite = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not finite:
        return None
    target = fraction * (len(finite) - 1)
    lower = math.floor(target)
    upper = math.ceil(target)
    index = lower if target - lower <= upper - target else upper
    return finite[index]


def paired_bootstrap_median(values: list[float], *, replicates: int, seed: int) -> dict:
    if not values:
        raise ValueError("U5a bootstrap requires scene values")
    rng = random.Random(seed)
    stats: list[float] = []
    for _ in range(replicates):
        sample = [values[rng.randrange(len(values))] for _ in range(len(values))]
        stats.append(float(statistics.median(sample)))
    return {
        "sceneValues": values,
        "median": float(statistics.median(values)),
        "replicates": replicates,
        "seed": seed,
        "lower95": nearest_tie_lower(stats, 0.025),
        "upper95": nearest_tie_lower(stats, 0.975),
    }


def target_metrics(rendered: np.ndarray, faro: np.ndarray) -> dict:
    rendered = np.asarray(rendered, dtype=np.float64)
    faro = np.asarray(faro, dtype=np.float64)
    if rendered.shape != faro.shape:
        raise ValueError("U5a rendered/FARO depth shapes differ")
    faro_valid = np.isfinite(faro) & (faro > 0.0)
    faro_count = int(np.count_nonzero(faro_valid))
    if faro_count == 0:
        raise ValueError("U5a FARO target has no valid depth pixels")
    rendered_valid = np.isfinite(rendered)
    overlap = faro_valid & rendered_valid
    overlap_count = int(np.count_nonzero(overlap))
    errors = np.abs(rendered[overlap] - faro[overlap])
    within5 = int(np.count_nonzero(errors <= 0.05))
    within10 = int(np.count_nonzero(errors <= 0.10))
    error_values = errors.tolist()
    return {
        "faroValidPixelCount": faro_count,
        "renderedFiniteOnFaroValidPixelCount": overlap_count,
        "coverageFraction": float(overlap_count / faro_count),
        "absoluteDepthErrorMeanMetres": None if errors.size == 0 else float(np.mean(errors)),
        "absoluteDepthErrorMedianMetres": None if errors.size == 0 else float(np.median(errors)),
        "absoluteDepthErrorP95Metres": nearest_tie_lower(error_values, 0.95),
        "within5cmFractionOfFaroValid": float(within5 / faro_count),
        "within10cmFractionOfFaroValid": float(within10 / faro_count),
    }


def mean_defined(records: list[dict], key: str) -> float | None:
    values = [float(record[key]) for record in records if record[key] is not None]
    return None if not values else float(statistics.mean(values))


def scene_summary(targets: list[dict]) -> dict:
    if len(targets) != 8:
        raise ValueError("U5a scene summary requires exactly eight target views")
    return {
        "targetViewCount": 8,
        "primaryWithin5cmFractionOfFaroValid": float(
            statistics.mean(float(record["within5cmFractionOfFaroValid"]) for record in targets)
        ),
        "within10cmFractionOfFaroValidMean": float(
            statistics.mean(float(record["within10cmFractionOfFaroValid"]) for record in targets)
        ),
        "coverageFractionMean": float(
            statistics.mean(float(record["coverageFraction"]) for record in targets)
        ),
        "absoluteDepthErrorMeanMetresAcrossTargetMeans": mean_defined(
            targets, "absoluteDepthErrorMeanMetres"
        ),
        "absoluteDepthErrorMedianMetresAcrossTargetMedians": mean_defined(
            targets, "absoluteDepthErrorMedianMetres"
        ),
        "absoluteDepthErrorP95MetresAcrossTargetP95": mean_defined(
            targets, "absoluteDepthErrorP95Metres"
        ),
    }


def validate_inputs(args: argparse.Namespace) -> tuple[dict, dict]:
    for path in (
        args.protocol,
        args.target_clarification,
        args.evaluation_clarification,
        args.preparation,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)
    if not args.render_tool.is_file():
        raise FileNotFoundError(args.render_tool)
    protocol = json.loads(args.protocol.read_text())
    if protocol.get("id") != STUDY_ID or not protocol.get("frozen"):
        raise ValueError("U5a protocol is not frozen")
    target_clarification = json.loads(args.target_clarification.read_text())
    if target_clarification.get("id") != TARGET_CLARIFICATION_ID or not target_clarification.get("frozen"):
        raise ValueError("U5a target-camera clarification is not frozen")
    evaluation_clarification = json.loads(args.evaluation_clarification.read_text())
    if evaluation_clarification.get("id") != EVAL_CLARIFICATION_ID or not evaluation_clarification.get("frozen"):
        raise ValueError("U5a evaluation clarification is not frozen")
    preparation = json.loads(args.preparation.read_text())
    if preparation.get("study") != STUDY_ID or preparation.get("status") != "prepared-no-u5a-render-or-metric-outcomes":
        raise ValueError("U5a preparation is not admissible")
    if preparation.get("protocolSha256") != sha256_file(args.protocol):
        raise ValueError("U5a preparation protocol SHA mismatch")
    if preparation.get("clarificationSha256") != sha256_file(args.target_clarification):
        raise ValueError("U5a preparation target clarification SHA mismatch")
    if not preparation.get("noRenderedDepthProduced") or not preparation.get("noU5aMetricsProduced"):
        raise ValueError("U5a preparation crossed the outcome boundary")
    return protocol, preparation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--target-clarification", type=Path, required=True)
    parser.add_argument("--evaluation-clarification", type=Path, required=True)
    parser.add_argument("--preparation", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--render-tool", type=Path, required=True)
    args = parser.parse_args()

    protocol, preparation = validate_inputs(args)
    result_path = args.output_root / "result.json"
    if result_path.exists():
        raise ValueError("U5a result.json already exists; exploratory outcome will not be overwritten")

    prep_by_scene = {record["scene"]: record for record in preparation["scenes"]}
    scene_results: dict[str, dict] = {}
    for scene in EXPECTED_SCENES:
        prep_scene = prep_by_scene.get(scene)
        if prep_scene is None:
            raise ValueError(f"U5a preparation is missing {scene}")
        scene_root = args.output_root / "scenes" / scene
        target_manifest = scene_root / "targets.json"
        if not target_manifest.is_file() or sha256_file(target_manifest) != prep_scene["targetManifestSha256"]:
            raise ValueError(f"U5a target manifest SHA mismatch for {scene}")
        target_payload = json.loads(target_manifest.read_text())
        targets = target_payload["targets"]
        if len(targets) != 8:
            raise ValueError(f"U5a {scene} does not have eight targets")
        method_results: dict[str, dict] = {}
        for method in METHODS:
            method_prep = prep_scene["methods"][method]
            gaussian_path = Path(method_prep["gaussianPath"])
            if not gaussian_path.is_file() or sha256_file(gaussian_path) != method_prep["gaussianSha256"]:
                raise ValueError(f"U5a Gaussian SHA mismatch for {scene} {method}")
            target_results: list[dict] = []
            for target in targets:
                target_index = int(target["targetIndex"])
                render_dir = scene_root / "renders" / method
                render_dir.mkdir(parents=True, exist_ok=True)
                rendered_path = render_dir / f"{target_index:02d}.f32"
                render_json = run_json(
                    [
                        str(args.render_tool),
                        str(gaussian_path),
                        str(target_manifest),
                        "--target-index",
                        str(target_index),
                        "--output",
                        str(rendered_path),
                        "--json",
                    ],
                    label=f"render {scene} {method} target {target_index}",
                )
                width = int(target["width"])
                height = int(target["height"])
                rendered = np.fromfile(rendered_path, dtype="<f4")
                faro_path = Path(target["faroDepthPath"])
                if not faro_path.is_file() or sha256_file(faro_path) != target["faroDepthSha256"]:
                    raise ValueError(f"U5a FARO depth SHA mismatch for {scene} target {target_index}")
                faro = np.fromfile(faro_path, dtype="<f4")
                expected = width * height
                if rendered.size != expected or faro.size != expected:
                    raise ValueError(f"U5a target byte count mismatch for {scene} target {target_index}")
                metrics = target_metrics(rendered.reshape(height, width), faro.reshape(height, width))
                record = {
                    "targetIndex": target_index,
                    "timestampNanoseconds": int(target["timestampNanoseconds"]),
                    "renderSha256": sha256_file(rendered_path),
                    "render": render_json,
                    **metrics,
                }
                target_results.append(record)
                print(
                    json.dumps(
                        {
                            "u5aMetric": {
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
            method_results[method] = {
                "gaussianSha256": method_prep["gaussianSha256"],
                "primitiveCount": int(method_prep["primitiveCount"]),
                "targets": target_results,
                "sceneSummary": scene_summary(target_results),
            }
        scene_results[scene] = {
            "targetManifestSha256": prep_scene["targetManifestSha256"],
            "methods": method_results,
        }

    candidate_vs_depth: list[float] = []
    candidate_vs_shuffled: list[float] = []
    candidate_better_depth = 0
    candidate_better_shuffled = 0
    for scene in EXPECTED_SCENES:
        methods = scene_results[scene]["methods"]
        depth_score = methods["depth-only-covariance"]["sceneSummary"]["primaryWithin5cmFractionOfFaroValid"]
        candidate_score = methods["calibrated-covariance"]["sceneSummary"]["primaryWithin5cmFractionOfFaroValid"]
        shuffled_score = methods["shuffled-calibrated-covariance"]["sceneSummary"]["primaryWithin5cmFractionOfFaroValid"]
        delta_depth = float(candidate_score - depth_score)
        delta_shuffled = float(candidate_score - shuffled_score)
        candidate_vs_depth.append(delta_depth)
        candidate_vs_shuffled.append(delta_shuffled)
        candidate_better_depth += int(delta_depth > 0.0)
        candidate_better_shuffled += int(delta_shuffled > 0.0)

    comparison = {
        "candidateMinusDepthOnly": paired_bootstrap_median(candidate_vs_depth, replicates=2000, seed=42),
        "candidateMinusShuffled": paired_bootstrap_median(candidate_vs_shuffled, replicates=2000, seed=42),
        "candidateBetterThanDepthOnlySceneCount": candidate_better_depth,
        "candidateBetterThanShuffledSceneCount": candidate_better_shuffled,
        "descriptiveOnly": True,
    }
    payload = {
        "schemaVersion": 1,
        "study": STUDY_ID,
        "stage": "U5a-exploratory-heldout-depth",
        "status": "completed-exploratory-gaussian-depth-study",
        "claimType": protocol["claimType"],
        "protocolSha256": sha256_file(args.protocol),
        "targetClarificationSha256": sha256_file(args.target_clarification),
        "evaluationClarificationSha256": sha256_file(args.evaluation_clarification),
        "preparationSha256": sha256_file(args.preparation),
        "renderToolSha256": sha256_file(args.render_tool),
        "scenes": scene_results,
        "descriptiveComparison": comparison,
        "claimBoundary": "Exploratory only on already-exposed rooms. A positive mechanism requires a separately frozen untouched U5b study before any efficacy claim.",
    }
    result_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
