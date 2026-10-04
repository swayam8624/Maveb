#!/usr/bin/env python3
"""Run the frozen U3 dense-CPU TSDF primary experiment in two explicit stages."""

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


METHODS = (
    "uniform",
    "naive-confidence",
    "calibrated-depth-only",
    "calibrated-inverse-variance",
    "calibrated-shuffled-confidence",
)
FROZEN_MODEL_SHA256 = "744cdfce9763f5d2ecd9c9a4e53385f66d8bba7cbc047e11729189053a85e17a"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_json(command: list[str], *, label: str) -> dict:
    print(json.dumps({"u3Progress": {"label": label, "command": command}}), file=sys.stderr, flush=True)
    completed = subprocess.run(command, text=True, capture_output=True)
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="", flush=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f"{label} failed with exit code {completed.returncode}: {completed.stdout.strip()}"
        )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"{label} produced no JSON output")
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} did not end in JSON: {lines[-1]}") from exc


def nearest_tie_lower_index(count: int, fraction: float) -> int:
    if count <= 0:
        raise ValueError("percentile requires non-empty values")
    target = fraction * (count - 1)
    lower = math.floor(target)
    upper = math.ceil(target)
    return lower if target - lower <= upper - target else upper


def percentile_nearest(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return float(ordered[nearest_tie_lower_index(len(ordered), fraction)])


def paired_bootstrap_median(values: list[float], *, replicates: int, seed: int) -> dict:
    if not values:
        raise ValueError("paired bootstrap requires scene values")
    rng = random.Random(seed)
    statistics_values = []
    for _ in range(replicates):
        sample = [values[rng.randrange(len(values))] for _ in range(len(values))]
        statistics_values.append(float(statistics.median(sample)))
    return {
        "sceneValues": values,
        "median": float(statistics.median(values)),
        "replicates": replicates,
        "seed": seed,
        "lower95": percentile_nearest(statistics_values, 0.025),
        "upper95": percentile_nearest(statistics_values, 0.975),
    }


def f_score_at(metrics: dict, threshold: float) -> float:
    for record in metrics["fScores"]:
        if abs(float(record["threshold"]) - threshold) <= 1.0e-12:
            return float(record["fScore"])
    raise ValueError(f"geometry report has no F-score at {threshold}")


def compact_geometry_metrics(report: dict, fuse: dict) -> dict:
    metrics = report["metrics"]
    return {
        "accuracyMeanMetres": float(metrics["accuracyMean"]),
        "completenessMeanMetres": float(metrics["completenessMean"]),
        "chamferMeanMetres": float(metrics["chamferMean"]),
        "fScore": f_score_at(metrics, 0.05),
        "elapsedMilliseconds": float(fuse["elapsedMilliseconds"]),
        "peakResidentBytes": int(fuse["peakResidentBytes"]),
        "vertices": int(fuse["vertices"]),
        "triangles": int(fuse["triangles"]),
    }


def prepare(args: argparse.Namespace, study: dict) -> dict:
    repo = Path(__file__).resolve().parents[2]
    adapter = repo / "benchmarks" / "scripts" / "prepare_u3_ca1m_scene.py"
    ledgers = []
    for scene in study["evaluationScenes"]:
        video_id = scene.rsplit("-", 1)[-1]
        archive = args.data_root / f"ca1m-val-{video_id}.tar"
        sidecar_root = args.confidence_root / "raw" / "Validation" / video_id
        scene_output = args.output_root / "scenes" / scene
        command = [
            sys.executable,
            str(adapter),
            str(archive),
            "--confidence-root",
            str(sidecar_root / "confidence"),
            "--lowres-depth-root",
            str(sidecar_root / "lowres_depth"),
            "--preflight",
            str(args.preflight),
            "--pose-gate",
            str(args.pose_gate),
            "--study",
            str(args.study),
            "--model",
            str(args.model),
            "--output-dir",
            str(scene_output),
        ]
        ledgers.append(run_json(command, label=f"prepare {scene}"))
    payload = {
        "schemaVersion": 1,
        "study": study["id"],
        "stage": "U3-primary-prepare",
        "status": "prepared-no-reconstruction-outcomes",
        "studySha256": sha256_file(args.study),
        "modelSha256": sha256_file(args.model),
        "preflightSha256": sha256_file(args.preflight),
        "poseGateSha256": sha256_file(args.pose_gate),
        "scenes": ledgers,
    }
    args.output_root.mkdir(parents=True, exist_ok=True)
    path = args.output_root / "primary-prepare-ledger.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    return payload


def evaluate(args: argparse.Namespace, study: dict) -> dict:
    if not args.fuse_tool.is_file():
        raise FileNotFoundError(args.fuse_tool)
    prepare_ledger_path = args.output_root / "primary-prepare-ledger.json"
    if not prepare_ledger_path.is_file():
        raise ValueError("U3 primary preparation ledger is missing; run --stage prepare first")
    prepare_ledger = json.loads(prepare_ledger_path.read_text())
    if prepare_ledger.get("status") != "prepared-no-reconstruction-outcomes":
        raise ValueError("U3 primary preparation ledger is not admissible")
    if prepare_ledger.get("modelSha256") != FROZEN_MODEL_SHA256:
        raise ValueError("U3 primary preparation used the wrong model")
    final_path = args.output_root / "primary-result.json"
    if final_path.exists():
        raise ValueError("primary-result.json already exists; frozen U3 primary outcome will not be overwritten")

    repo = Path(__file__).resolve().parents[2]
    geometry_script = repo / "benchmarks" / "scripts" / "evaluate_geometry.py"
    scene_results: dict[str, dict] = {}
    for scene in study["evaluationScenes"]:
        scene_dir = args.output_root / "scenes" / scene
        manifest = scene_dir / "scene-manifest.json"
        reference = scene_dir / "reference-faro.ply"
        if not manifest.is_file() or not reference.is_file():
            raise ValueError(f"prepared U3 assets are missing for {scene}")
        method_results: dict[str, dict] = {}
        for method in METHODS:
            method_dir = scene_dir / "primary" / method
            method_dir.mkdir(parents=True, exist_ok=True)
            mesh = method_dir / "mesh.ply"
            fuse = run_json(
                [
                    str(args.fuse_tool),
                    str(manifest),
                    "--mode",
                    method,
                    "--output",
                    str(mesh),
                    "--json",
                ],
                label=f"fuse {scene} {method}",
            )
            (method_dir / "fusion.json").write_text(json.dumps(fuse, indent=2, sort_keys=True) + "\n")
            geometry = run_json(
                [
                    sys.executable,
                    str(geometry_script),
                    str(mesh),
                    str(reference),
                    "--align",
                    "none",
                    "--thresholds",
                    "0.05",
                    "--max-points",
                    str(study["referenceSampling"]["maximumReferencePoints"]),
                    "--seed",
                    "42",
                ],
                label=f"geometry {scene} {method}",
            )
            (method_dir / "geometry.json").write_text(
                json.dumps(geometry, indent=2, sort_keys=True) + "\n"
            )
            method_results[method] = {
                "metrics": compact_geometry_metrics(geometry, fuse),
                "meshSha256": sha256_file(mesh),
                "fusion": fuse,
                "geometry": geometry,
            }
            print(
                json.dumps({
                    "u3PrimaryMetric": {
                        "scene": scene,
                        "method": method,
                        "chamferMeanMetres": method_results[method]["metrics"]["chamferMeanMetres"],
                        "fScore": method_results[method]["metrics"]["fScore"],
                    }
                }),
                file=sys.stderr,
                flush=True,
            )
        scene_results[scene] = {
            "manifestSha256": sha256_file(manifest),
            "referenceSha256": sha256_file(reference),
            "methods": method_results,
        }

    relative_improvements = []
    shuffled_degradations = []
    depth_only_improvements = []
    for scene in study["evaluationScenes"]:
        methods = scene_results[scene]["methods"]
        naive = methods["naive-confidence"]["metrics"]["chamferMeanMetres"]
        intact = methods["calibrated-inverse-variance"]["metrics"]["chamferMeanMetres"]
        shuffled = methods["calibrated-shuffled-confidence"]["metrics"]["chamferMeanMetres"]
        depth_only = methods["calibrated-depth-only"]["metrics"]["chamferMeanMetres"]
        if naive <= 0.0 or intact <= 0.0:
            raise ValueError("Chamfer must be positive for relative U3 comparisons")
        relative_improvements.append((naive - intact) / naive)
        shuffled_degradations.append((shuffled - intact) / intact)
        depth_only_improvements.append((naive - depth_only) / naive)

    comparison = study["primaryComparison"]
    improvement_bootstrap = paired_bootstrap_median(
        relative_improvements,
        replicates=int(comparison["pairedSceneBootstrapReplicates"]),
        seed=int(comparison["pairedSceneBootstrapSeed"]),
    )
    shuffled_bootstrap = paired_bootstrap_median(
        shuffled_degradations,
        replicates=int(comparison["pairedSceneBootstrapReplicates"]),
        seed=int(comparison["pairedSceneBootstrapSeed"]),
    )
    depth_only_bootstrap = paired_bootstrap_median(
        depth_only_improvements,
        replicates=int(comparison["pairedSceneBootstrapReplicates"]),
        seed=int(comparison["pairedSceneBootstrapSeed"]),
    )
    positive_gate = comparison["positiveGeometryGate"]
    shuffled_rule = positive_gate["calibratedShuffledConfidenceMustBeMateriallyWorse"]
    shuffled_worse_count = sum(value > 0.0 for value in shuffled_degradations)
    gate_checks = {
        "medianRelativeChamferImprovementAtLeastThreshold":
            improvement_bootstrap["median"] >= float(positive_gate["minimumMedianRelativeChamferImprovement"]),
        "relativeChamferImprovementLower95AboveZero": improvement_bootstrap["lower95"] > 0.0,
        "shuffledWorseSceneCountAtLeastThreshold":
            shuffled_worse_count >= int(shuffled_rule["minimumWorseSceneCount"]),
        "shuffledRelativeDegradationLower95AboveZero": shuffled_bootstrap["lower95"] > 0.0,
    }
    passed = all(gate_checks.values())
    result = {
        "schemaVersion": 1,
        "study": study["id"],
        "stage": "U3-dense-cpu-primary-8view",
        "status": "passed-positive-geometry-gate" if passed else "completed-primary-gate-not-passed",
        "studySha256": sha256_file(args.study),
        "modelSha256": sha256_file(args.model),
        "preflightSha256": sha256_file(args.preflight),
        "poseGateSha256": sha256_file(args.pose_gate),
        "fuseTool": str(args.fuse_tool),
        "fuseToolSha256": sha256_file(args.fuse_tool),
        "scenes": scene_results,
        "primaryComparison": {
            "relativeChamferImprovementIntactVsNaive": improvement_bootstrap,
            "relativeChamferDegradationShuffledVsIntact": {
                **shuffled_bootstrap,
                "shuffledWorseSceneCount": shuffled_worse_count,
            },
            "relativeChamferImprovementDepthOnlyVsNaive": depth_only_bootstrap,
            "gateChecks": gate_checks,
            "passed": passed,
        },
    }
    temporary = final_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    temporary.replace(final_path)
    print(json.dumps(result, sort_keys=True))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("prepare", "evaluate"), required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--confidence-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--study",
        type=Path,
        default=Path("benchmarks/experiments/metric-uncertainty-u3-dense-tsdf-v1.json"),
    )
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--pose-gate", type=Path, required=True)
    parser.add_argument("--fuse-tool", type=Path, default=Path("build/ci/tools/maveb-u3-fuse/maveb-u3-fuse"))
    args = parser.parse_args()

    for path in (args.study, args.model, args.preflight, args.pose_gate):
        if not path.is_file():
            raise FileNotFoundError(path)
    if sha256_file(args.model) != FROZEN_MODEL_SHA256:
        raise ValueError("U3 requires the exact frozen U1b model")
    study = json.loads(args.study.read_text())
    if study.get("status") != "preregistered-before-real-u3-geometry-outcomes" or not study.get("frozen"):
        raise ValueError("U3 study is not frozen for primary evaluation")
    if args.stage == "prepare":
        prepare(args, study)
    else:
        evaluate(args, study)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
