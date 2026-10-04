#!/usr/bin/env python3
"""Run frozen U3b confirmatory dense-CPU TSDF preparation/evaluation in explicit stages."""

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


STUDY_ID = "metric-uncertainty-u3b-relative-confidence-transfer-v1"
STUDY_SHA256 = "f42fb12bb855e660c3cf4d77e5dd4200b73136baa73981434b54c98b43e63a6d"
MODEL_SHA256 = "744cdfce9763f5d2ecd9c9a4e53385f66d8bba7cbc047e11729189053a85e17a"
POSE_SHA256 = "692479544ceff75e02fd3645138eab5a5e38d83e397ff3ec5de9ce1a3d468f6d"
ACQUISITION_SHA256 = "3675d61e89599a36641e8d4ddb0dd28ce9722030af3b4672b70c401973695f73"
METHODS = (
    "uniform",
    "naive-confidence",
    "u3v1-absolute-inverse-variance",
    "relative-confidence-precision",
    "relative-confidence-shuffled",
)
ENGINE_MAPPING = {
    "uniform": ("relative", "uniform"),
    "naive-confidence": ("relative", "naive-confidence"),
    "u3v1-absolute-inverse-variance": ("legacy", "calibrated-inverse-variance"),
    "relative-confidence-precision": ("relative", "calibrated-inverse-variance"),
    "relative-confidence-shuffled": ("relative", "calibrated-shuffled-confidence"),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_json(command: list[str], *, label: str) -> dict:
    print(json.dumps({"u3bProgress": {"label": label, "command": command}}), file=sys.stderr, flush=True)
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
    stats = []
    for _ in range(replicates):
        sample = [values[rng.randrange(len(values))] for _ in range(len(values))]
        stats.append(float(statistics.median(sample)))
    return {
        "sceneValues": values,
        "median": float(statistics.median(values)),
        "replicates": replicates,
        "seed": seed,
        "lower95": percentile_nearest(stats, 0.025),
        "upper95": percentile_nearest(stats, 0.975),
    }


def f_score_at(metrics: dict, threshold: float) -> float:
    for record in metrics["fScores"]:
        if abs(float(record["threshold"]) - threshold) <= 1e-12:
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


def load_runtime_replay_snapshot(path: Path | None) -> tuple[dict[tuple[str, str], dict], str | None]:
    if path is None:
        return {}, None
    if not path.is_file():
        raise FileNotFoundError(path)
    snapshot = json.loads(path.read_text())
    if snapshot.get("study") != STUDY_ID:
        raise ValueError("runtime recovery snapshot study mismatch")
    if snapshot.get("status") != "frozen-pre-fix-partial-reveal":
        raise ValueError("runtime recovery snapshot is not frozen pre-fix evidence")
    if int(snapshot.get("completedMethodCount", -1)) != 16:
        raise ValueError("runtime recovery snapshot must contain exactly 16 completed methods")
    expectations: dict[tuple[str, str], dict] = {}
    for record in snapshot.get("completed", []):
        key = (str(record["scene"]), str(record["method"]))
        if key in expectations:
            raise ValueError(f"duplicate runtime replay expectation: {key}")
        expectations[key] = record
    if len(expectations) != 16:
        raise ValueError("runtime recovery snapshot completed list must contain exactly 16 methods")
    return expectations, sha256_file(path)


def verify_runtime_replay(
    expected: dict,
    *,
    scene: str,
    method: str,
    mesh_sha256: str,
    metrics: dict,
) -> None:
    if mesh_sha256 != expected["meshSha256"]:
        raise RuntimeError(
            f"runtime recovery mesh mismatch for {scene} {method}: "
            f"{mesh_sha256} != {expected['meshSha256']}"
        )
    if abs(metrics["chamferMeanMetres"] - float(expected["chamferMeanMetres"])) > 1e-12:
        raise RuntimeError(f"runtime recovery Chamfer mismatch for {scene} {method}")
    if abs(metrics["fScore"] - float(expected["fScoreAt5cm"])) > 1e-12:
        raise RuntimeError(f"runtime recovery F-score mismatch for {scene} {method}")
    if metrics["vertices"] != int(expected["vertices"]) or metrics["triangles"] != int(expected["triangles"]):
        raise RuntimeError(f"runtime recovery topology-count mismatch for {scene} {method}")


def validate_inputs(args: argparse.Namespace) -> tuple[dict, dict]:
    for path in (args.study, args.model, args.pose_preflight, args.acquisition_ledger, args.adapter):
        if not path.is_file():
            raise FileNotFoundError(path)
    if sha256_file(args.study) != STUDY_SHA256:
        raise ValueError("U3b study SHA differs from the preregistered protocol")
    if sha256_file(args.model) != MODEL_SHA256:
        raise ValueError("U3b requires the exact frozen U1b model")
    if sha256_file(args.pose_preflight) != POSE_SHA256:
        raise ValueError("U3b requires the exact frozen passed pose artifact")
    if sha256_file(args.acquisition_ledger) != ACQUISITION_SHA256:
        raise ValueError("U3b acquisition ledger SHA differs from the frozen acquired artifact")
    study = json.loads(args.study.read_text())
    if study.get("id") != STUDY_ID or not study.get("frozen"):
        raise ValueError("U3b study is not frozen")
    acquisition = json.loads(args.acquisition_ledger.read_text())
    if acquisition.get("status") != "acquired-after-clean-preregistered-plan":
        raise ValueError("U3b acquisition ledger is not admissible")
    if acquisition.get("study") != STUDY_ID:
        raise ValueError("U3b acquisition ledger study mismatch")
    adapter = json.loads(args.adapter.read_text())
    if adapter.get("study") != STUDY_ID or adapter.get("status") != "frozen-before-any-u3b-reconstruction-outcome":
        raise ValueError("U3b engine adapter is not the frozen pre-outcome adapter")
    return study, acquisition


def prepare(args: argparse.Namespace, study: dict, acquisition: dict) -> dict:
    repo = Path(__file__).resolve().parents[2]
    adapter_script = repo / "benchmarks/scripts/prepare_u3b_ca1m_scene.py"
    acquisition_by_video = {str(entry["videoId"]): entry for entry in acquisition["entries"]}
    ledgers = []
    for item in study["confirmatorySplit"]["videos"]:
        video_id = str(item["videoId"])
        scene = f"ca1m-{video_id}"
        acquired = acquisition_by_video.get(video_id)
        if acquired is None:
            raise ValueError(f"acquisition ledger is missing {video_id}")
        archive = Path(acquired["ca1mArchive"])
        if not archive.is_file() or sha256_file(archive) != acquired["ca1mArchiveSha256"]:
            raise ValueError(f"acquired CA-1M archive hash mismatch for {video_id}")
        sidecar_root = args.confidence_root / "raw" / "Validation" / video_id
        scene_output = args.output_root / "scenes" / scene
        ledger = run_json(
            [
                sys.executable,
                str(adapter_script),
                str(archive),
                "--confidence-root",
                str(sidecar_root / "confidence"),
                "--lowres-depth-root",
                str(sidecar_root / "lowres_depth"),
                "--pose-preflight",
                str(args.pose_preflight),
                "--study",
                str(args.study),
                "--model",
                str(args.model),
                "--adapter",
                str(args.adapter),
                "--output-dir",
                str(scene_output),
            ],
            label=f"prepare {scene}",
        )
        if ledger.get("archiveSha256") != acquired["ca1mArchiveSha256"]:
            raise ValueError(f"prepared archive SHA does not match acquisition ledger for {video_id}")
        ledgers.append(ledger)

    payload = {
        "schemaVersion": 1,
        "study": STUDY_ID,
        "stage": "U3b-primary-prepare",
        "status": "prepared-no-reconstruction-outcomes",
        "studySha256": sha256_file(args.study),
        "modelSha256": sha256_file(args.model),
        "posePreflightSha256": sha256_file(args.pose_preflight),
        "acquisitionLedgerSha256": sha256_file(args.acquisition_ledger),
        "engineAdapterSha256": sha256_file(args.adapter),
        "scenes": ledgers,
    }
    args.output_root.mkdir(parents=True, exist_ok=True)
    path = args.output_root / "primary-prepare-ledger.json"
    if (args.output_root / "primary-result.json").exists():
        raise ValueError("U3b primary outcome already exists; preparation will not be rewritten")
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    return payload


def evaluate(args: argparse.Namespace, study: dict) -> dict:
    if not args.fuse_tool.is_file():
        raise FileNotFoundError(args.fuse_tool)
    prepare_path = args.output_root / "primary-prepare-ledger.json"
    if not prepare_path.is_file():
        raise ValueError("U3b preparation ledger is missing; run --stage prepare first")
    prep = json.loads(prepare_path.read_text())
    required_hashes = {
        "studySha256": STUDY_SHA256,
        "modelSha256": MODEL_SHA256,
        "posePreflightSha256": POSE_SHA256,
        "acquisitionLedgerSha256": ACQUISITION_SHA256,
        "engineAdapterSha256": sha256_file(args.adapter),
    }
    if prep.get("status") != "prepared-no-reconstruction-outcomes":
        raise ValueError("U3b preparation ledger is not admissible")
    for key, value in required_hashes.items():
        if prep.get(key) != value:
            raise ValueError(f"U3b preparation ledger {key} mismatch")
    final_path = args.output_root / "primary-result.json"
    if final_path.exists():
        raise ValueError("primary-result.json already exists; frozen U3b outcome will not be overwritten")

    replay_expectations, replay_snapshot_sha256 = load_runtime_replay_snapshot(
        args.runtime_recovery_snapshot
    )
    existing_meshes = list(args.output_root.glob("scenes/*/primary/*/mesh.ply"))
    if existing_meshes and not replay_expectations:
        raise ValueError(
            "partial U3b primary artifacts already exist; a frozen runtime recovery snapshot is required"
        )
    replay_verified = 0

    repo = Path(__file__).resolve().parents[2]
    geometry_script = repo / "benchmarks/scripts/evaluate_geometry.py"
    scene_results: dict[str, dict] = {}
    for item in study["confirmatorySplit"]["videos"]:
        video_id = str(item["videoId"])
        scene = f"ca1m-{video_id}"
        scene_dir = args.output_root / "scenes" / scene
        reference = scene_dir / "reference-faro.ply"
        legacy_manifest = scene_dir / "scene-manifest-legacy.json"
        relative_manifest = scene_dir / "scene-manifest-relative.json"
        if not all(path.is_file() for path in (reference, legacy_manifest, relative_manifest)):
            raise ValueError(f"prepared U3b assets are missing for {scene}")
        method_results: dict[str, dict] = {}
        for method in METHODS:
            manifest_role, engine_mode = ENGINE_MAPPING[method]
            manifest = legacy_manifest if manifest_role == "legacy" else relative_manifest
            method_dir = scene_dir / "primary" / method
            method_dir.mkdir(parents=True, exist_ok=True)
            mesh = method_dir / "mesh.ply"
            fuse = run_json(
                [
                    str(args.fuse_tool),
                    str(manifest),
                    "--mode",
                    engine_mode,
                    "--output",
                    str(mesh),
                    "--json",
                ],
                label=f"fuse {scene} {method}",
            )
            mesh_sha256 = sha256_file(mesh)
            replay_expected = replay_expectations.get((scene, method))
            if replay_expected is not None and mesh_sha256 != replay_expected["meshSha256"]:
                raise RuntimeError(
                    f"runtime recovery mesh mismatch for {scene} {method}: "
                    f"{mesh_sha256} != {replay_expected['meshSha256']}"
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
                    str(study["volumeAndReference"]["maximumReferencePoints"]),
                    "--seed",
                    "42",
                ],
                label=f"geometry {scene} {method}",
            )
            (method_dir / "geometry.json").write_text(json.dumps(geometry, indent=2, sort_keys=True) + "\n")
            metrics = compact_geometry_metrics(geometry, fuse)
            if replay_expected is not None:
                verify_runtime_replay(
                    replay_expected,
                    scene=scene,
                    method=method,
                    mesh_sha256=mesh_sha256,
                    metrics=metrics,
                )
                replay_verified += 1
                if replay_verified == len(replay_expectations):
                    print(
                        json.dumps(
                            {
                                "u3bRuntimeRecovery": {
                                    "status": "pre-failure-replay-verified",
                                    "methods": replay_verified,
                                    "snapshotSha256": replay_snapshot_sha256,
                                }
                            }
                        ),
                        file=sys.stderr,
                        flush=True,
                    )
            method_results[method] = {
                "engineManifestRole": manifest_role,
                "engineMode": engine_mode,
                "engineManifestSha256": sha256_file(manifest),
                "metrics": metrics,
                "meshSha256": mesh_sha256,
                "fusion": fuse,
                "geometry": geometry,
            }
            print(
                json.dumps(
                    {
                        "u3bPrimaryMetric": {
                            "scene": scene,
                            "method": method,
                            "chamferMeanMetres": metrics["chamferMeanMetres"],
                            "fScore": metrics["fScore"],
                        }
                    }
                ),
                file=sys.stderr,
                flush=True,
            )
        scene_results[scene] = {
            "referenceSha256": sha256_file(reference),
            "legacyManifestSha256": sha256_file(legacy_manifest),
            "relativeManifestSha256": sha256_file(relative_manifest),
            "methods": method_results,
        }

    if replay_expectations and replay_verified != len(replay_expectations):
        raise RuntimeError(
            f"runtime recovery replay verified {replay_verified} methods, expected {len(replay_expectations)}"
        )

    improvements = []
    shuffled_degradations = []
    legacy_improvements = []
    for item in study["confirmatorySplit"]["videos"]:
        scene = f"ca1m-{item['videoId']}"
        methods = scene_results[scene]["methods"]
        naive = methods["naive-confidence"]["metrics"]["chamferMeanMetres"]
        candidate = methods["relative-confidence-precision"]["metrics"]["chamferMeanMetres"]
        shuffled = methods["relative-confidence-shuffled"]["metrics"]["chamferMeanMetres"]
        legacy = methods["u3v1-absolute-inverse-variance"]["metrics"]["chamferMeanMetres"]
        if naive <= 0.0 or candidate <= 0.0:
            raise ValueError("Chamfer must be positive for U3b relative comparisons")
        improvements.append((naive - candidate) / naive)
        shuffled_degradations.append((shuffled - candidate) / candidate)
        legacy_improvements.append((naive - legacy) / naive)

    comparison = study["primaryComparison"]
    replicates = int(comparison["pairedSceneBootstrapReplicates"])
    seed = int(comparison["pairedSceneBootstrapSeed"])
    improvement_bootstrap = paired_bootstrap_median(improvements, replicates=replicates, seed=seed)
    shuffled_bootstrap = paired_bootstrap_median(shuffled_degradations, replicates=replicates, seed=seed)
    legacy_bootstrap = paired_bootstrap_median(legacy_improvements, replicates=replicates, seed=seed)
    gate = comparison["positiveConfirmatoryGate"]
    candidate_wins = sum(value > 0.0 for value in improvements)
    shuffled_worse = sum(value > 0.0 for value in shuffled_degradations)
    gate_checks = {
        "medianRelativeChamferImprovementAtLeastThreshold":
            improvement_bootstrap["median"] >= float(gate["minimumMedianRelativeChamferImprovement"]),
        "relativeChamferImprovementLower95AboveZero": improvement_bootstrap["lower95"] > 0.0,
        "candidateBeatsNaiveSceneCountAtLeastThreshold":
            candidate_wins >= int(gate["candidateMustBeatNaiveInAtLeastScenes"]),
        "shuffledWorseSceneCountAtLeastThreshold":
            shuffled_worse >= int(gate["shuffledControl"]["shuffledMustBeWorseInAtLeastScenes"]),
        "shuffledRelativeDegradationLower95AboveZero": shuffled_bootstrap["lower95"] > 0.0,
    }
    passed = all(gate_checks.values())
    result = {
        "schemaVersion": 1,
        "study": STUDY_ID,
        "stage": "U3b-confirmatory-dense-cpu-primary-8view",
        "status": "passed-positive-confirmatory-gate" if passed else "completed-confirmatory-gate-not-passed",
        "studySha256": STUDY_SHA256,
        "modelSha256": MODEL_SHA256,
        "posePreflightSha256": POSE_SHA256,
        "acquisitionLedgerSha256": ACQUISITION_SHA256,
        "engineAdapterSha256": sha256_file(args.adapter),
        "prepareLedgerSha256": sha256_file(prepare_path),
        "fuseTool": str(args.fuse_tool),
        "fuseToolSha256": sha256_file(args.fuse_tool),
        "scenes": scene_results,
        "primaryComparison": {
            "relativeChamferImprovementCandidateVsNaive": {
                **improvement_bootstrap,
                "candidateBetterSceneCount": candidate_wins,
            },
            "relativeChamferDegradationShuffledVsCandidate": {
                **shuffled_bootstrap,
                "shuffledWorseSceneCount": shuffled_worse,
            },
            "relativeChamferImprovementLegacyU3v1VsNaive": legacy_bootstrap,
            "gateChecks": gate_checks,
            "passed": passed,
        },
    }
    if replay_snapshot_sha256 is not None:
        result["runtimeRecovery"] = {
            "status": "pre-failure-replay-verified",
            "snapshotSha256": replay_snapshot_sha256,
            "verifiedMethodCount": replay_verified,
            "requireExactMeshSha256": True,
            "metricTolerance": 1e-12,
        }
    temporary = final_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    temporary.replace(final_path)
    print(json.dumps(result, sort_keys=True))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("prepare", "evaluate"), required=True)
    parser.add_argument("--confidence-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--study",
        type=Path,
        default=Path("benchmarks/experiments/metric-uncertainty-u3b-relative-confidence-transfer-v1.json"),
    )
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--pose-preflight", type=Path, required=True)
    parser.add_argument("--acquisition-ledger", type=Path, required=True)
    parser.add_argument(
        "--adapter",
        type=Path,
        default=Path("benchmarks/experiments/metric-uncertainty-u3b-engine-adapter-v1.json"),
    )
    parser.add_argument(
        "--fuse-tool",
        type=Path,
        default=Path("build/ci/tools/maveb-u3-fuse/maveb-u3-fuse"),
    )
    parser.add_argument(
        "--runtime-recovery-snapshot",
        type=Path,
        help="frozen pre-fix partial-reveal snapshot; required when primary meshes already exist",
    )
    args = parser.parse_args()

    study, acquisition = validate_inputs(args)
    if args.stage == "prepare":
        prepare(args, study, acquisition)
    else:
        evaluate(args, study)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
