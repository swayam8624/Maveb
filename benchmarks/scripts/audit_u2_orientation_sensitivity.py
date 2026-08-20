#!/usr/bin/env python3
"""Post-hoc sensitivity audit for U2 sidecar orientation quality.

The primary U2 result is already frozen and MUST NOT be replaced by this analysis. This script asks
whether the held-out intact-vs-control result survives after restricting evaluation to frames whose
ARKitScenes raw-depth orientation witness lies inside the maximum median disagreement observed on
U1 calibration frames (51 mm), and/or to each scene's modal discrete sidecar transform.

These subsets are diagnostic only. They may expose a sidecar-association artifact but may not be used
to retune the model, replace held-out scenes, or redefine the primary U2 claim.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import argparse
import hashlib
import json
from pathlib import Path

import compare_uncertainty_controls as compare_controls
import uncertainty_metrics as metrics


MODES = ("intact", "constant", "shuffled")
SUBSETS = ("within-calibration-witness-envelope", "modal-transform-only", "strict-intersection")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_frame_profiles(controlled_path: Path) -> dict[str, dict]:
    frames: dict[str, dict[int, tuple[str, float]]] = defaultdict(dict)
    with controlled_path.open("r", encoding="utf-8") as stream:
        for line_number, raw in enumerate(stream, start=1):
            if not raw.strip():
                continue
            row = json.loads(raw)
            scene = str(row["scene"])
            timestamp = int(row["timestampNanoseconds"])
            transform = str(row["sidecarOrientationTransform"])
            witness_mm = float(row["orientationWitnessMedianAbsErrorMillimetres"])
            prior = frames[scene].get(timestamp)
            value = (transform, witness_mm)
            if prior is not None and prior != value:
                raise ValueError(
                    f"inconsistent orientation metadata within frame {scene}/{timestamp} at line {line_number}"
                )
            frames[scene][timestamp] = value

    result = {}
    for scene, scene_frames in sorted(frames.items()):
        transforms = Counter(transform for transform, _ in scene_frames.values())
        if not transforms:
            raise ValueError(f"scene has no frames: {scene}")
        modal_transform = sorted(transforms, key=lambda name: (-transforms[name], name))[0]
        witness_values = [value[1] for value in scene_frames.values()]
        result[scene] = {
            "frameCount": len(scene_frames),
            "modalTransform": modal_transform,
            "transformFrameCounts": dict(sorted(transforms.items())),
            "maximumWitnessMedianAbsErrorMillimetres": max(witness_values),
        }
    return result


def include_row(row: dict, subset: str, profiles: dict[str, dict], threshold_mm: float) -> bool:
    scene = str(row["scene"])
    witness_mm = float(row["orientationWitnessMedianAbsErrorMillimetres"])
    transform = str(row["sidecarOrientationTransform"])
    inside = witness_mm <= threshold_mm
    modal = transform == profiles[scene]["modalTransform"]
    if subset == "within-calibration-witness-envelope":
        return inside
    if subset == "modal-transform-only":
        return modal
    if subset == "strict-intersection":
        return inside and modal
    raise ValueError(f"unknown sensitivity subset: {subset}")


def evaluate_mode(
    controlled_path: Path,
    predictions_path: Path,
    profiles: dict[str, dict],
    *,
    threshold_mm: float,
    student_t_df: float,
) -> tuple[dict[str, dict], dict]:
    samples: dict[str, dict[str, list[metrics.ErrorSample]]] = {
        subset: defaultdict(list) for subset in SUBSETS
    }
    sample_counts = {subset: Counter() for subset in SUBSETS}
    frame_sets = {subset: defaultdict(set) for subset in SUBSETS}

    with controlled_path.open("r", encoding="utf-8") as controls, predictions_path.open(
        "r", encoding="utf-8"
    ) as predictions:
        control_iter = (line for line in controls if line.strip())
        prediction_iter = (line for line in predictions if line.strip())
        for line_number, pair in enumerate(zip(control_iter, prediction_iter, strict=True), start=1):
            control_row = json.loads(pair[0])
            prediction_row = json.loads(pair[1])
            if str(control_row.get("sampleId")) != str(prediction_row.get("sampleId")):
                raise ValueError(f"sample-order mismatch at paired line {line_number}")
            if str(control_row.get("scene")) != str(prediction_row.get("scene")):
                raise ValueError(f"scene mismatch at paired line {line_number}")
            scene = str(control_row["scene"])
            timestamp = int(control_row["timestampNanoseconds"])
            sample = metrics.ErrorSample(
                predicted_sigma_metres=float(prediction_row["predictedSigmaMetres"]),
                signed_error_metres=float(prediction_row["signedErrorMetres"]),
                scene=scene,
                method=str(prediction_row.get("method", "unknown")),
            )
            for subset in SUBSETS:
                if include_row(control_row, subset, profiles, threshold_mm):
                    samples[subset][scene].append(sample)
                    sample_counts[subset][scene] += 1
                    frame_sets[subset][scene].add(timestamp)

    reports = {}
    subset_meta = {}
    for subset in SUBSETS:
        scene_metrics = {}
        for scene in sorted(profiles):
            values = samples[subset].get(scene, [])
            if not values:
                raise ValueError(f"sensitivity subset {subset} removed all samples from {scene}")
            scene_metrics[scene] = metrics.evaluate(values, bin_count=10, student_t_df=student_t_df)
        reports[subset] = scene_metrics
        subset_meta[subset] = {
            "sampleCounts": dict(sorted(sample_counts[subset].items())),
            "frameCounts": {scene: len(frame_sets[subset][scene]) for scene in sorted(profiles)},
        }
    return reports, subset_meta


def compare_subset(mode_reports: dict[str, dict[str, dict]], subset: str, bootstrap: int, seed: int) -> dict:
    intact = mode_reports["intact"][subset]
    constant = mode_reports["constant"][subset]
    shuffled = mode_reports["shuffled"][subset]
    return {
        "intactVsConstant": compare_controls.compare(
            intact, constant, control_name="constant", replicates=bootstrap, seed=seed
        ),
        "intactVsShuffled": compare_controls.compare(
            intact, shuffled, control_name="shuffled", replicates=bootstrap, seed=seed
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--calibration-witness-max-mm", type=float, default=51.0)
    parser.add_argument("--student-t-df", type=float, default=3.0)
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    try:
        root = args.output_root.resolve()
        intact_controlled = root / "held-out/intact/controlled-method.jsonl"
        profiles = discover_frame_profiles(intact_controlled)
        mode_reports = {}
        mode_meta = {}
        input_hashes = {}
        for mode in MODES:
            controlled = root / f"held-out/{mode}/controlled-method.jsonl"
            predictions = root / f"held-out/{mode}/predictions.jsonl"
            if not controlled.is_file() or not predictions.is_file():
                raise ValueError(f"missing frozen U2 artifacts for mode {mode}")
            reports, metadata = evaluate_mode(
                controlled,
                predictions,
                profiles,
                threshold_mm=args.calibration_witness_max_mm,
                student_t_df=args.student_t_df,
            )
            mode_reports[mode] = reports
            mode_meta[mode] = metadata
            input_hashes[mode] = {
                "controlledMethodSha256": sha256_file(controlled),
                "predictionsSha256": sha256_file(predictions),
            }

        comparisons = {
            subset: compare_subset(mode_reports, subset, args.bootstrap, args.seed)
            for subset in SUBSETS
        }
        result = {
            "schemaVersion": 1,
            "analysisType": "post-hoc-sensitivity-not-primary-U2",
            "primaryU2Unchanged": True,
            "calibrationWitnessEnvelopeMaximumMillimetres": args.calibration_witness_max_mm,
            "studentTDegreesOfFreedom": args.student_t_df,
            "bootstrapReplicates": args.bootstrap,
            "bootstrapSeed": args.seed,
            "frameProfiles": profiles,
            "inputHashes": input_hashes,
            "subsetMetadata": mode_meta,
            "comparisons": comparisons,
        }
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"audit_u2_orientation_sensitivity: {exc}")
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"ok": True, "output": str(args.output.resolve())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
