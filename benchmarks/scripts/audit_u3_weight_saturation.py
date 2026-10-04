#!/usr/bin/env python3
"""Post-hoc diagnostic of the frozen U3 uncertainty-to-TSDF precision mapping.

This script does not rerun reconstruction, inspect FARO geometry, or alter any frozen
model/study artifact. It only reads the already-prepared eight-view depth/confidence
inputs and reports how the preregistered inverse-variance mapping distributes weights.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


EXPECTED_PRIMARY_STATUS = "completed-primary-gate-not-passed"
CONFIDENCE_LEVELS = (0, 128, 255)
DEPTH_BINS = (
    (0.05, 1.0, "0.05-1m"),
    (1.0, 2.0, "1-2m"),
    (2.0, 3.0, "2-3m"),
    (3.0, 5.0, "3-5m"),
    (5.0, 20.000001, "5-20m"),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_weights(
    depth_metres: np.ndarray,
    confidence_u8: np.ndarray,
    config: dict,
    *,
    sensor_confidence_penalty: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    depth = np.asarray(depth_metres, dtype=np.float64)
    confidence = np.asarray(confidence_u8, dtype=np.float64) / 255.0
    penalty = (
        float(config["sensorConfidencePenalty"])
        if sensor_confidence_penalty is None
        else float(sensor_confidence_penalty)
    )
    base_sensor_sigma = (
        float(config["depthNoiseFloorMetres"])
        + float(config["depthNoiseQuadraticMetresPerMetreSquared"]) * depth * depth
    )
    sensor_sigma = base_sensor_sigma * (1.0 + penalty * (1.0 - confidence))
    pose_sigma = float(config["poseTranslationFloorMetres"])
    sigma = np.sqrt(sensor_sigma * sensor_sigma + pose_sigma * pose_sigma)
    sigma = np.clip(
        sigma,
        float(config["minimumSigmaMetres"]),
        float(config["maximumSigmaMetres"]),
    )
    raw_precision = (float(config["referenceSigmaMetres"]) / sigma) ** 2
    weights = np.clip(
        raw_precision,
        float(config["minimumPrecisionWeight"]),
        float(config["maximumPrecisionWeight"]),
    )
    return sigma, weights


def summary(weights: np.ndarray, sigma: np.ndarray, minimum: float, maximum: float) -> dict:
    if weights.size == 0:
        return {"count": 0}
    return {
        "count": int(weights.size),
        "fractionAtMinimumPrecisionWeight": float(np.mean(np.isclose(weights, minimum, rtol=0.0, atol=1e-12))),
        "fractionAtMaximumPrecisionWeight": float(np.mean(np.isclose(weights, maximum, rtol=0.0, atol=1e-12))),
        "medianPrecisionWeight": float(np.median(weights)),
        "p10PrecisionWeight": float(np.quantile(weights, 0.10)),
        "p90PrecisionWeight": float(np.quantile(weights, 0.90)),
        "medianPredictedSigmaMetres": float(np.median(sigma)),
    }


def analyse_scene(scene_dir: Path) -> tuple[dict, dict[str, np.ndarray]]:
    manifest_path = scene_dir / "scene-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    config = manifest["uncertainty"]
    minimum = float(config["minimumPrecisionWeight"])
    maximum = float(config["maximumPrecisionWeight"])
    minimum_depth = float(manifest["volume"]["minimumDepthMetres"])
    maximum_depth = float(manifest["volume"]["maximumDepthMetres"])

    depths: list[np.ndarray] = []
    confidences: list[np.ndarray] = []
    for frame in manifest["frames"]:
        count = int(frame["width"]) * int(frame["height"])
        depth = np.fromfile(scene_dir / frame["depthPath"], dtype="<f4", count=count).astype(np.float64)
        confidence = np.fromfile(scene_dir / frame["confidencePath"], dtype=np.uint8, count=count)
        if depth.size != count or confidence.size != count:
            raise ValueError(f"prepared U3 frame has unexpected size in {scene_dir.name}")
        valid = np.isfinite(depth) & (depth >= minimum_depth) & (depth <= maximum_depth)
        depths.append(depth[valid])
        confidences.append(confidence[valid])

    depth = np.concatenate(depths) if depths else np.empty(0, dtype=np.float64)
    confidence = np.concatenate(confidences) if confidences else np.empty(0, dtype=np.uint8)
    if depth.size == 0:
        raise ValueError(f"scene {scene_dir.name} has no valid prepared depth samples")
    unexpected = sorted(set(int(value) for value in np.unique(confidence)) - set(CONFIDENCE_LEVELS))
    if unexpected:
        raise ValueError(f"scene {scene_dir.name} has unexpected confidence values: {unexpected}")

    sigma, weights = compute_weights(depth, confidence, config)
    _, depth_only_weights = compute_weights(depth, confidence, config, sensor_confidence_penalty=0.0)
    delta = np.abs(weights - depth_only_weights)

    result = {
        "scene": scene_dir.name,
        "manifestSha256": sha256_file(manifest_path),
        "validPreparedSamples": int(depth.size),
        "overall": summary(weights, sigma, minimum, maximum),
        "comparisonToCalibratedDepthOnly": {
            "meanAbsolutePrecisionWeightDifference": float(np.mean(delta)),
            "medianAbsolutePrecisionWeightDifference": float(np.median(delta)),
            "fractionExactlyEqualWithin1e12": float(np.mean(delta <= 1e-12)),
        },
        "byConfidenceU8": {},
        "byDepthBinAndConfidenceU8": {},
    }
    for level in CONFIDENCE_LEVELS:
        mask = confidence == level
        record = summary(weights[mask], sigma[mask], minimum, maximum)
        record["fractionOfValidPreparedSamples"] = float(np.mean(mask))
        if np.any(mask):
            local_delta = delta[mask]
            record["meanAbsoluteDifferenceFromDepthOnly"] = float(np.mean(local_delta))
            record["fractionExactlyEqualToDepthOnlyWithin1e12"] = float(np.mean(local_delta <= 1e-12))
        result["byConfidenceU8"][str(level)] = record

    for lower, upper, label in DEPTH_BINS:
        bin_record: dict[str, dict] = {}
        in_bin = (depth >= lower) & (depth < upper)
        for level in CONFIDENCE_LEVELS:
            mask = in_bin & (confidence == level)
            bin_record[str(level)] = summary(weights[mask], sigma[mask], minimum, maximum)
        result["byDepthBinAndConfidenceU8"][label] = bin_record

    arrays = {
        "depth": depth,
        "confidence": confidence,
        "sigma": sigma,
        "weights": weights,
        "depthOnlyWeights": depth_only_weights,
    }
    return result, arrays


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    primary_result = args.output_root / "primary-result.json"
    prepare_ledger = args.output_root / "primary-prepare-ledger.json"
    if not primary_result.is_file() or not prepare_ledger.is_file():
        raise ValueError("U3 primary result and preparation ledger are required")
    primary = json.loads(primary_result.read_text())
    if primary.get("status") != EXPECTED_PRIMARY_STATUS:
        raise ValueError("weight-saturation audit is defined only after the frozen negative U3 primary result")
    prepared = json.loads(prepare_ledger.read_text())
    scene_ids = [record["scene"] for record in prepared["scenes"]]

    scene_results = []
    aggregate_arrays: dict[str, list[np.ndarray]] = {
        "depth": [],
        "confidence": [],
        "sigma": [],
        "weights": [],
        "depthOnlyWeights": [],
    }
    for scene in scene_ids:
        result, arrays = analyse_scene(args.output_root / "scenes" / scene)
        scene_results.append(result)
        for key, value in arrays.items():
            aggregate_arrays[key].append(value)

    depth = np.concatenate(aggregate_arrays["depth"])
    confidence = np.concatenate(aggregate_arrays["confidence"])
    sigma = np.concatenate(aggregate_arrays["sigma"])
    weights = np.concatenate(aggregate_arrays["weights"])
    depth_only = np.concatenate(aggregate_arrays["depthOnlyWeights"])
    first_manifest = json.loads(
        (args.output_root / "scenes" / scene_ids[0] / "scene-manifest.json").read_text()
    )
    config = first_manifest["uncertainty"]
    minimum = float(config["minimumPrecisionWeight"])
    maximum = float(config["maximumPrecisionWeight"])
    delta = np.abs(weights - depth_only)

    aggregate = {
        "validPreparedSamples": int(depth.size),
        "overall": summary(weights, sigma, minimum, maximum),
        "comparisonToCalibratedDepthOnly": {
            "meanAbsolutePrecisionWeightDifference": float(np.mean(delta)),
            "medianAbsolutePrecisionWeightDifference": float(np.median(delta)),
            "fractionExactlyEqualWithin1e12": float(np.mean(delta <= 1e-12)),
        },
        "byConfidenceU8": {},
        "byDepthBinAndConfidenceU8": {},
    }
    for level in CONFIDENCE_LEVELS:
        mask = confidence == level
        record = summary(weights[mask], sigma[mask], minimum, maximum)
        record["fractionOfValidPreparedSamples"] = float(np.mean(mask))
        if np.any(mask):
            local_delta = delta[mask]
            record["meanAbsoluteDifferenceFromDepthOnly"] = float(np.mean(local_delta))
            record["fractionExactlyEqualToDepthOnlyWithin1e12"] = float(np.mean(local_delta <= 1e-12))
        aggregate["byConfidenceU8"][str(level)] = record
    for lower, upper, label in DEPTH_BINS:
        in_bin = (depth >= lower) & (depth < upper)
        aggregate["byDepthBinAndConfidenceU8"][label] = {
            str(level): summary(weights[in_bin & (confidence == level)], sigma[in_bin & (confidence == level)], minimum, maximum)
            for level in CONFIDENCE_LEVELS
        }

    payload = {
        "schemaVersion": 1,
        "study": "metric-uncertainty-v1",
        "stage": "U3-post-hoc-weight-saturation-audit",
        "status": "diagnostic-only-no-geometry-rerun",
        "primaryResultSha256": sha256_file(primary_result),
        "prepareLedgerSha256": sha256_file(prepare_ledger),
        "method": "Recompute only the preregistered per-sample calibrated precision weights from frozen prepared depth/confidence inputs. FARO geometry and primary metrics are not inputs to this diagnostic.",
        "scenes": scene_results,
        "aggregate": aggregate,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(args.output)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
