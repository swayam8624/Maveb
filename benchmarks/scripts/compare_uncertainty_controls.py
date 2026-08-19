#!/usr/bin/env python3
"""Compare held-out uncertainty controls with paired scene-level bootstrap.

This is the paper-level U2 comparison: pixels are used to compute each scene's metrics, but scenes are
resampled as the evidence unit. The script is frozen before held-out sidecar acquisition.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import random


METRICS = {
    "studentTNll": "lower",
    "gaussianNll": "lower",
    "expectedCalibrationErrorMetres": "lower",
    "pearsonSigmaAbsoluteError": "higher",
    "sharpnessRmsSigmaMetres": "descriptive",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_scene_metrics(path: Path) -> dict[str, dict]:
    payload = json.loads(path.read_text())
    groups = payload.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError(f"report contains no metric groups: {path}")
    scenes: dict[str, dict] = {}
    for record in groups:
        group = record.get("group", {})
        scene = str(group.get("scene", ""))
        metrics = record.get("metrics", {})
        if not scene:
            raise ValueError(f"report group is missing scene: {path}")
        if scene in scenes:
            raise ValueError(f"duplicate scene in report: {scene}")
        if "studentTNll" not in metrics:
            raise ValueError(f"report lacks preregistered Student-t score: {path}")
        scenes[scene] = metrics
    return scenes


def percentile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("percentile requires values")
    ordered = sorted(values)
    index = probability * (len(ordered) - 1)
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    fraction = index - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def paired_bootstrap(
    differences: dict[str, float], *, replicates: int, seed: int
) -> dict:
    if replicates <= 0:
        raise ValueError("bootstrap replicates must be positive")
    scenes = sorted(differences)
    if not scenes:
        raise ValueError("paired bootstrap requires scenes")
    observed = [differences[scene] for scene in scenes]
    rng = random.Random(seed)
    distribution = []
    for _ in range(replicates):
        draw = [observed[rng.randrange(len(observed))] for _ in observed]
        distribution.append(sum(draw) / len(draw))
    return {
        "meanDifference": sum(observed) / len(observed),
        "medianDifference": percentile(observed, 0.5),
        "lower95": percentile(distribution, 0.025),
        "upper95": percentile(distribution, 0.975),
        "sceneCount": len(observed),
    }


def compare(
    intact: dict[str, dict],
    control: dict[str, dict],
    *,
    control_name: str,
    replicates: int,
    seed: int,
) -> dict:
    if set(intact) != set(control):
        raise ValueError(f"{control_name} scene set differs from intact")
    scenes = sorted(intact)
    comparisons = {}
    for metric, direction in METRICS.items():
        differences = {}
        for scene in scenes:
            left = intact[scene].get(metric)
            right = control[scene].get(metric)
            if left is None or right is None:
                if metric == "pearsonSigmaAbsoluteError":
                    continue
                raise ValueError(f"missing {metric} for scene {scene}")
            differences[scene] = float(left) - float(right)
        if not differences:
            continue
        record = paired_bootstrap(differences, replicates=replicates, seed=seed)
        record["direction"] = direction
        record["perSceneDifferenceIntactMinusControl"] = dict(sorted(differences.items()))
        if direction == "lower":
            record["intactBetterSceneCount"] = sum(value < 0.0 for value in differences.values())
        elif direction == "higher":
            record["intactBetterSceneCount"] = sum(value > 0.0 for value in differences.values())
        comparisons[metric] = record

    for scene in scenes:
        intact_rmse = float(intact[scene]["empiricalRmseMetres"])
        control_rmse = float(control[scene]["empiricalRmseMetres"])
        if not math.isclose(intact_rmse, control_rmse, rel_tol=0.0, abs_tol=1.0e-12):
            raise ValueError(
                f"control changed empirical error samples for {scene}: {intact_rmse} vs {control_rmse}"
            )
    return {"control": control_name, "scenes": scenes, "comparisons": comparisons}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intact", type=Path, required=True)
    parser.add_argument("--constant", type=Path, required=True)
    parser.add_argument("--shuffled", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    try:
        intact = load_scene_metrics(args.intact)
        constant = load_scene_metrics(args.constant)
        shuffled = load_scene_metrics(args.shuffled)
        result = {
            "schemaVersion": 1,
            "evidenceUnit": "scene",
            "differenceConvention": "intact minus control",
            "bootstrapReplicates": args.bootstrap,
            "bootstrapSeed": args.seed,
            "inputSha256": {
                "intact": sha256_file(args.intact),
                "constant": sha256_file(args.constant),
                "shuffled": sha256_file(args.shuffled),
            },
            "intactVsConstant": compare(
                intact, constant, control_name="constant", replicates=args.bootstrap, seed=args.seed
            ),
            "intactVsShuffled": compare(
                intact, shuffled, control_name="shuffled", replicates=args.bootstrap, seed=args.seed
            ),
        }
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"compare_uncertainty_controls: {exc}")
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"ok": True, "output": str(args.output.resolve())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
