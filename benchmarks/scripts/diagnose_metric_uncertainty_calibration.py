#!/usr/bin/env python3
"""Diagnose calibration-model saturation before any held-out evaluation.

This tool is intentionally read-only with respect to the fitted model. It summarizes empirical
ARKit-vs-FARO depth error, confidence strata, depth strata, predicted-sigma saturation, and the
incremental calibration value of confidence on the calibration set. It is designed to answer a
specific gate question: is the fitted U1 sensor model numerically and structurally credible enough
that we should expose the frozen held-out scenes?
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

import geometric_uncertainty as uncertainty


DEPTH_BINS = ((0.0, 1.0), (1.0, 2.0), (2.0, 3.0), (3.0, 5.0), (5.0, 10.0), (10.0, 20.0))


def load_rows(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, raw in enumerate(stream, start=1):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL line {line_number}: {path}") from exc
            rows.append(row)
    if not rows:
        raise ValueError("calibration observations are empty")
    return rows


def predict_sigma(rows: list[dict], config: uncertainty.UncertaintyModelConfig) -> np.ndarray:
    depth = np.asarray([float(row["depthMetres"]) for row in rows], dtype=np.float64)
    sensor_conf = np.asarray([float(row["sensorConfidence"]) for row in rows], dtype=np.float64)
    pose_conf = np.asarray([float(row["poseConfidence"]) for row in rows], dtype=np.float64)
    reproj = np.asarray([float(row["reprojectionErrorPixels"]) for row in rows], dtype=np.float64)
    focal = np.asarray([float(row["focalLengthPixels"]) for row in rows], dtype=np.float64)
    align_pos = np.asarray([float(row.get("alignmentPositionRmseMetres", 0.0)) for row in rows], dtype=np.float64)
    align_rot = np.asarray([float(row.get("alignmentOrientationErrorDegrees", 0.0)) for row in rows], dtype=np.float64)

    sensor = (
        config.depth_noise_floor_metres
        + config.depth_noise_quadratic_metres_per_metre_squared * depth * depth
    ) * (1.0 + config.sensor_confidence_penalty * (1.0 - sensor_conf))
    pose = config.pose_translation_floor_metres + config.pose_translation_scale_metres * (1.0 - pose_conf)
    reproj_sigma = depth * reproj / focal
    align_rot_sigma = depth * np.tan(np.radians(align_rot))
    sigma = np.sqrt(sensor * sensor + pose * pose + reproj_sigma * reproj_sigma + align_pos * align_pos + align_rot_sigma * align_rot_sigma)
    return np.clip(sigma, config.minimum_sigma_metres, config.maximum_sigma_metres)


def summarize(
    errors: np.ndarray,
    sigma: np.ndarray | None = None,
    maximum_sigma_metres: float | None = None,
) -> dict:
    absolute = np.abs(errors)
    result = {
        "count": int(errors.size),
        "biasMetres": float(np.mean(errors)),
        "maeMetres": float(np.mean(absolute)),
        "rmseMetres": float(np.sqrt(np.mean(errors * errors))),
        "medianAbsErrorMetres": float(np.median(absolute)),
        "p90AbsErrorMetres": float(np.quantile(absolute, 0.90)),
        "p95AbsErrorMetres": float(np.quantile(absolute, 0.95)),
        "p99AbsErrorMetres": float(np.quantile(absolute, 0.99)),
        "fractionAbsErrorOver025m": float(np.mean(absolute > 0.25)),
        "fractionAbsErrorOver050m": float(np.mean(absolute > 0.50)),
        "fractionAbsErrorOver100m": float(np.mean(absolute > 1.00)),
    }
    if sigma is not None:
        cap = maximum_sigma_metres if maximum_sigma_metres is not None else float(np.max(sigma))
        capped = np.isclose(sigma, cap, rtol=0.0, atol=1e-12)
        result.update(
            {
                "sigmaRmsMetres": float(np.sqrt(np.mean(sigma * sigma))),
                "sigmaMedianMetres": float(np.median(sigma)),
                "fractionAtMaximumSigma": float(np.mean(capped)),
                "coverage1Sigma": float(np.mean(absolute <= sigma)),
                "coverage2Sigma": float(np.mean(absolute <= 2.0 * sigma)),
                "pearsonSigmaAbsError": float(np.corrcoef(sigma, absolute)[0, 1]) if errors.size > 1 and np.std(sigma) > 0 and np.std(absolute) > 0 else 0.0,
            }
        )
    return result


def gaussian_nll(errors: np.ndarray, sigma: np.ndarray) -> float:
    return float(np.mean(np.log(sigma) + 0.5 * (errors / sigma) ** 2 + 0.5 * math.log(2.0 * math.pi)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("observations", type=Path)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    rows = load_rows(args.observations.resolve())
    model_payload = json.loads(args.model.read_text())
    config = uncertainty.config_from_json(model_payload)

    scenes = np.asarray([str(row["scene"]) for row in rows], dtype=object)
    depth = np.asarray([float(row["depthMetres"]) for row in rows], dtype=np.float64)
    raw_confidence = np.asarray([int(row.get("rawSensorConfidenceLevel", round(float(row["sensorConfidence"]) * 2.0))) for row in rows], dtype=np.int64)
    errors = np.asarray([float(row["signedErrorMetres"]) for row in rows], dtype=np.float64)
    sigma = predict_sigma(rows, config)

    no_conf_config = uncertainty.UncertaintyModelConfig(**{
        **config.__dict__,
        "sensor_confidence_penalty": 0.0,
    })
    sigma_no_conf = predict_sigma(rows, no_conf_config)

    per_scene = {}
    for scene in sorted(set(scenes.tolist())):
        mask = scenes == scene
        per_scene[scene] = summarize(errors[mask], sigma[mask], config.maximum_sigma_metres)
        per_scene[scene]["gaussianNllFitted"] = gaussian_nll(errors[mask], sigma[mask])
        per_scene[scene]["gaussianNllSameDepthTermsNoConfidence"] = gaussian_nll(errors[mask], sigma_no_conf[mask])

    by_confidence = {}
    for level in (0, 1, 2):
        mask = raw_confidence == level
        if np.any(mask):
            by_confidence[str(level)] = summarize(errors[mask], sigma[mask], config.maximum_sigma_metres)

    by_depth = {}
    for lower, upper in DEPTH_BINS:
        mask = (depth >= lower) & (depth < upper)
        if np.any(mask):
            by_depth[f"[{lower:g},{upper:g})"] = summarize(errors[mask], sigma[mask], config.maximum_sigma_metres)

    fitted_nll = gaussian_nll(errors, sigma)
    no_conf_nll = gaussian_nll(errors, sigma_no_conf)
    report = {
        "schemaVersion": 1,
        "status": "calibration-diagnostic-only-no-held-out-data",
        "modelPath": str(args.model.resolve()),
        "modelConfig": uncertainty.config_to_json(config),
        "boundaryFlags": {
            "depthNoiseFloorAtOriginalUpperBound": config.depth_noise_floor_metres >= 0.099999,
            "depthNoiseQuadraticAtOriginalUpperBound": config.depth_noise_quadratic_metres_per_metre_squared >= 0.049999,
            "maximumSigmaMetres": config.maximum_sigma_metres,
        },
        "aggregate": summarize(errors, sigma, config.maximum_sigma_metres),
        "aggregateGaussianNllFitted": fitted_nll,
        "aggregateGaussianNllSameDepthTermsNoConfidence": no_conf_nll,
        "confidenceIncrementNll": no_conf_nll - fitted_nll,
        "perScene": per_scene,
        "byRawConfidenceLevel": by_confidence,
        "byDepthMetres": by_depth,
    }

    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
