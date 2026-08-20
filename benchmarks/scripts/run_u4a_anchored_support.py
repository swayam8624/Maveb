#!/usr/bin/env python3
"""Run frozen U4a anchored-support exploratory geometry after preparation is frozen."""

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


STUDY_ID = "metric-uncertainty-u4a-anchored-support-v1"
PROTOCOL_SHA256 = "c2edc6bcf81b7e2e3b1fb2b7a5ba6a32f1025ab17c95c4efdaa18a7fa4cb793b"
PREPARATION_SHA256 = "01a505be16f9f89b533f6ac45f300ba86cb0ab18417e2792d97569050d87fd90"
U3B_RESULT_SHA256 = "1b5e1635eb7491658a63058ca9cdeb0e1b4260bec049601c7c168fdca9ac165f"
U3C_SUMMARY_SHA256 = "652b2df1ae3811f23252af4469089ab4a2bd56ca12cdbea8e864b3d149505110"
METHODS = (
    "depth-only-anchored-support",
    "calibrated-anchored-support",
    "shuffled-calibrated-anchored-support",
)
EXPECTED_SCENES = (
    "ca1m-48458481",
    "ca1m-48018737",
    "ca1m-45261587",
    "ca1m-42897538",
    "ca1m-48018375",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_json(command: list[str], *, label: str) -> dict:
    print(json.dumps({"u4aProgress": {"label": label, "command": command}}), file=sys.stderr, flush=True)
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


def fscore_record(report: dict, threshold: float = 0.05) -> dict:
    for record in report["metrics"]["fScores"]:
        if abs(float(record["threshold"]) - threshold) <= 1e-12:
            return {
                "thresholdMetres": threshold,
                "precision": float(record["precision"]),
                "recall": float(record["recall"]),
                "fScore": float(record["fScore"]),
            }
    raise ValueError(f"geometry report has no F-score at {threshold}")


def compact_geometry(report: dict, fuse: dict) -> dict:
    metrics = report["metrics"]
    fscore = fscore_record(report)
    return {
        "accuracyMeanMetres": float(metrics["accuracyMean"]),
        "completenessMeanMetres": float(metrics["completenessMean"]),
        "chamferMeanMetres": float(metrics["chamferMean"]),
        "precisionAt5cm": fscore["precision"],
        "recallAt5cm": fscore["recall"],
        "fScoreAt5cm": fscore["fScore"],
        "vertices": int(fuse["vertices"]),
        "triangles": int(fuse["triangles"]),
        "elapsedMilliseconds": float(fuse["elapsedMilliseconds"]),
        "peakResidentBytes": int(fuse["peakResidentBytes"]),
        "zeroUpdateFramesSkipped": int(fuse.get("zeroUpdateFramesSkipped", 0)),
    }


def topology_metrics(mesh_path: Path) -> dict:
    import open3d as o3d

    mesh = o3d.io.read_triangle_mesh(str(mesh_path), enable_post_processing=False)
    triangle_count = len(mesh.triangles)
    if triangle_count == 0:
        return {
            "connectedComponentCount": 0,
            "largestConnectedComponentTriangleFraction": None,
        }
    labels, counts, _ = mesh.cluster_connected_triangles()
    component_count = len(counts)
    largest = max(int(value) for value in counts) if counts else 0
    return {
        "connectedComponentCount": int(component_count),
        "largestConnectedComponentTriangleFraction": float(largest / triangle_count),
    }


def relative_improvement(baseline: float, candidate: float) -> float:
    if not math.isfinite(baseline) or not math.isfinite(candidate) or baseline <= 0.0:
        raise ValueError("relative improvement requires finite positive baseline")
    return (baseline - candidate) / baseline


def validate_inputs(args: argparse.Namespace) -> tuple[dict, dict, dict]:
    for path in (args.protocol, args.preparation, args.u3b_result, args.u3c_summary):
        if not path.is_file():
            raise FileNotFoundError(path)
    if sha256_file(args.protocol) != PROTOCOL_SHA256:
        raise ValueError("U4a protocol SHA mismatch")
    if sha256_file(args.preparation) != PREPARATION_SHA256:
        raise ValueError("U4a preparation SHA mismatch")
    if sha256_file(args.u3b_result) != U3B_RESULT_SHA256:
        raise ValueError("U4a requires the exact frozen U3b result")
    if sha256_file(args.u3c_summary) != U3C_SUMMARY_SHA256:
        raise ValueError("U4a requires the exact frozen U3c summary")
    protocol = json.loads(args.protocol.read_text())
    preparation = json.loads(args.preparation.read_text())
    u3b = json.loads(args.u3b_result.read_text())
    if protocol.get("id") != STUDY_ID or not protocol.get("frozen"):
        raise ValueError("U4a protocol is not frozen")
    if preparation.get("status") != "prepared-no-u4a-geometry-outcomes":
        raise ValueError("U4a preparation is not admissible")
    if preparation.get("noGeometryOutcomesProduced") is not True:
        raise ValueError("U4a preparation did not preserve the no-geometry boundary")
    if [scene["scene"] for scene in preparation["scenes"]] != list(EXPECTED_SCENES):
        raise ValueError("U4a preparation scene order mismatch")
    if u3b.get("status") != "completed-confirmatory-gate-not-passed":
        raise ValueError("U4a source U3b result is not the frozen negative result")
    return protocol, preparation, u3b


def load_naive_baseline(scene: str, u3b_root: Path, u3b: dict) -> dict:
    geometry_path = u3b_root / "scenes" / scene / "primary" / "naive-confidence" / "geometry.json"
    mesh_path = u3b_root / "scenes" / scene / "primary" / "naive-confidence" / "mesh.ply"
    if not geometry_path.is_file() or not mesh_path.is_file():
        raise FileNotFoundError(f"U4a naive baseline artifacts missing for {scene}")
    geometry = json.loads(geometry_path.read_text())
    stored = u3b["scenes"][scene]["methods"]["naive-confidence"]["metrics"]
    chamfer = float(geometry["metrics"]["chamferMean"])
    if abs(chamfer - float(stored["chamferMeanMetres"])) > 1e-12:
        raise ValueError(f"U4a naive baseline geometry mismatch for {scene}")
    fscore = fscore_record(geometry)
    if abs(fscore["fScore"] - float(stored["fScore"])) > 1e-12:
        raise ValueError(f"U4a naive baseline F-score mismatch for {scene}")
    return {
        "meshSha256": sha256_file(mesh_path),
        "geometrySha256": sha256_file(geometry_path),
        "metrics": {
            "accuracyMeanMetres": float(geometry["metrics"]["accuracyMean"]),
            "completenessMeanMetres": float(geometry["metrics"]["completenessMean"]),
            "chamferMeanMetres": chamfer,
            "precisionAt5cm": fscore["precision"],
            "recallAt5cm": fscore["recall"],
            "fScoreAt5cm": fscore["fScore"],
            "vertices": int(stored["vertices"]),
            "triangles": int(stored["triangles"]),
            **topology_metrics(mesh_path),
        },
    }


def evaluate(args: argparse.Namespace, protocol: dict, preparation: dict, u3b: dict) -> dict:
    if not args.fuse_tool.is_file():
        raise FileNotFoundError(args.fuse_tool)
    final_path = args.output_root / "geometry-result.json"
    if final_path.exists():
        raise ValueError("U4a geometry-result.json already exists; exploratory outcome will not be overwritten")
    repo = Path(__file__).resolve().parents[2]
    geometry_script = repo / "benchmarks/scripts/evaluate_geometry.py"
    scene_results: dict[str, dict] = {}

    prep_by_scene = {item["scene"]: item for item in preparation["scenes"]}
    for scene in EXPECTED_SCENES:
        source_scene = args.u3b_root / "scenes" / scene
        reference = source_scene / "reference-faro.ply"
        if not reference.is_file():
            raise FileNotFoundError(reference)
        baseline = load_naive_baseline(scene, args.u3b_root, u3b)
        methods: dict[str, dict] = {}
        for method in METHODS:
            prep_method = prep_by_scene[scene]["methods"][method]
            method_root = args.output_root / "scenes" / scene / method
            manifest = method_root / "scene-manifest.json"
            if not manifest.is_file() or sha256_file(manifest) != prep_method["manifestSha256"]:
                raise ValueError(f"U4a prepared manifest mismatch for {scene} {method}")
            mesh = method_root / "mesh.ply"
            fuse = run_json(
                [
                    str(args.fuse_tool),
                    str(manifest),
                    "--mode",
                    "naive-confidence",
                    "--output",
                    str(mesh),
                    "--json",
                ],
                label=f"fuse {scene} {method}",
            )
            (method_root / "fusion.json").write_text(json.dumps(fuse, indent=2, sort_keys=True) + "\n")
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
                    "200000",
                    "--seed",
                    "42",
                ],
                label=f"geometry {scene} {method}",
            )
            geometry_path = method_root / "geometry.json"
            geometry_path.write_text(json.dumps(geometry, indent=2, sort_keys=True) + "\n")
            metrics = compact_geometry(geometry, fuse)
            metrics.update(topology_metrics(mesh))
            methods[method] = {
                "manifestSha256": prep_method["manifestSha256"],
                "anchorFieldSha256": prep_method["anchorFieldSha256"],
                "meshSha256": sha256_file(mesh),
                "fusionSha256": sha256_file(method_root / "fusion.json"),
                "geometrySha256": sha256_file(geometry_path),
                "supportDiagnostics": prep_method["diagnostics"],
                "metrics": metrics,
            }
            print(
                json.dumps(
                    {
                        "u4aMetric": {
                            "scene": scene,
                            "method": method,
                            "chamferMeanMetres": metrics["chamferMeanMetres"],
                            "precisionAt5cm": metrics["precisionAt5cm"],
                            "recallAt5cm": metrics["recallAt5cm"],
                            "connectedComponentCount": metrics["connectedComponentCount"],
                        }
                    }
                ),
                flush=True,
            )
        scene_results[scene] = {"naive-confidence": baseline, "methods": methods}

    candidate_vs_naive = []
    candidate_vs_depth_only = []
    shuffled_degradation = []
    for scene in EXPECTED_SCENES:
        candidate = scene_results[scene]["methods"]["calibrated-anchored-support"]["metrics"]["chamferMeanMetres"]
        naive = scene_results[scene]["naive-confidence"]["metrics"]["chamferMeanMetres"]
        depth_only = scene_results[scene]["methods"]["depth-only-anchored-support"]["metrics"]["chamferMeanMetres"]
        shuffled = scene_results[scene]["methods"]["shuffled-calibrated-anchored-support"]["metrics"]["chamferMeanMetres"]
        candidate_vs_naive.append(relative_improvement(naive, candidate))
        candidate_vs_depth_only.append(relative_improvement(depth_only, candidate))
        shuffled_degradation.append((shuffled - candidate) / candidate)

    comparison = {
        "candidateVsNaive": paired_bootstrap_median(candidate_vs_naive, replicates=2000, seed=42),
        "candidateVsDepthOnly": paired_bootstrap_median(candidate_vs_depth_only, replicates=2000, seed=42),
        "shuffledDegradationVsCandidate": paired_bootstrap_median(shuffled_degradation, replicates=2000, seed=42),
        "candidateBetterThanNaiveSceneCount": int(sum(value > 0.0 for value in candidate_vs_naive)),
        "candidateBetterThanDepthOnlySceneCount": int(sum(value > 0.0 for value in candidate_vs_depth_only)),
        "shuffledWorseThanCandidateSceneCount": int(sum(value > 0.0 for value in shuffled_degradation)),
        "descriptiveOnly": True,
    }
    payload = {
        "schemaVersion": 1,
        "study": STUDY_ID,
        "stage": "U4a-exploratory-geometry",
        "status": "completed-exploratory-geometry-study",
        "claimType": protocol["claimType"],
        "protocolSha256": sha256_file(args.protocol),
        "preparationSha256": sha256_file(args.preparation),
        "u3bPrimaryResultSha256": sha256_file(args.u3b_result),
        "u3cSummarySha256": sha256_file(args.u3c_summary),
        "fuseToolSha256": sha256_file(args.fuse_tool),
        "scenes": scene_results,
        "descriptiveComparison": comparison,
        "claimBoundary": "Exploratory study on already-exposed scenes. This result cannot establish efficacy; any positive mechanism must be tested on a separately frozen untouched U4b set.",
    }
    args.output_root.mkdir(parents=True, exist_ok=True)
    temporary = final_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(final_path)
    print(json.dumps(payload, sort_keys=True))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--u3b-root", type=Path, required=True)
    parser.add_argument("--u3c-summary", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--preparation", type=Path, required=True)
    parser.add_argument("--u3b-result", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--fuse-tool", type=Path, required=True)
    args = parser.parse_args()
    try:
        protocol, preparation, u3b = validate_inputs(args)
        evaluate(args, protocol, preparation, u3b)
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
