#!/usr/bin/env python3
"""Deterministic reference model for metric geometric uncertainty.

This module is intentionally independent from Maveb's production fusion path. It is the research
oracle used to turn observable sensor/alignment quantities into a predicted 1-sigma metric error.
Parameters are hypotheses, not claims: fit them on a calibration split, freeze them, then evaluate
on disjoint scenes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import json
import math
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class UncertaintyModelConfig:
    minimum_sigma_metres: float = 0.001
    maximum_sigma_metres: float = 0.25
    depth_noise_floor_metres: float = 0.002
    depth_noise_quadratic_metres_per_metre_squared: float = 0.0015
    sensor_confidence_penalty: float = 2.0
    pose_translation_floor_metres: float = 0.001
    pose_translation_scale_metres: float = 0.02
    reference_sigma_metres: float = 0.01
    minimum_precision_weight: float = 0.01
    maximum_precision_weight: float = 1.0


@dataclass(frozen=True)
class UncertaintyObservation:
    depth_metres: float
    sensor_confidence: float
    pose_confidence: float
    reprojection_error_pixels: float
    focal_length_pixels: float
    alignment_position_rmse_metres: float = 0.0
    alignment_orientation_error_degrees: float = 0.0


@dataclass(frozen=True)
class UncertaintyPrediction:
    sigma_metres: float
    variance_metres_squared: float
    precision_weight: float
    sensor_sigma_metres: float
    pose_translation_sigma_metres: float
    reprojection_sigma_metres: float
    alignment_position_sigma_metres: float
    alignment_rotation_sigma_metres: float


def _require_finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")


def validate_config(config: UncertaintyModelConfig) -> None:
    for name, value in asdict(config).items():
        _require_finite(name, value)
    if config.minimum_sigma_metres <= 0.0:
        raise ValueError("minimum_sigma_metres must be positive")
    if config.maximum_sigma_metres < config.minimum_sigma_metres:
        raise ValueError("maximum_sigma_metres must be >= minimum_sigma_metres")
    if config.depth_noise_floor_metres < 0.0:
        raise ValueError("depth_noise_floor_metres must be non-negative")
    if config.depth_noise_quadratic_metres_per_metre_squared < 0.0:
        raise ValueError("depth noise quadratic coefficient must be non-negative")
    if config.sensor_confidence_penalty < 0.0:
        raise ValueError("sensor_confidence_penalty must be non-negative")
    if config.pose_translation_floor_metres < 0.0 or config.pose_translation_scale_metres < 0.0:
        raise ValueError("pose translation sigmas must be non-negative")
    if config.reference_sigma_metres <= 0.0:
        raise ValueError("reference_sigma_metres must be positive")
    if config.minimum_precision_weight <= 0.0:
        raise ValueError("minimum_precision_weight must be positive")
    if config.maximum_precision_weight < config.minimum_precision_weight:
        raise ValueError("maximum_precision_weight must be >= minimum_precision_weight")


def validate_observation(observation: UncertaintyObservation) -> None:
    for name, value in asdict(observation).items():
        _require_finite(name, value)
    if observation.depth_metres <= 0.0:
        raise ValueError("depth_metres must be positive")
    if not 0.0 <= observation.sensor_confidence <= 1.0:
        raise ValueError("sensor_confidence must be in [0, 1]")
    if not 0.0 <= observation.pose_confidence <= 1.0:
        raise ValueError("pose_confidence must be in [0, 1]")
    if observation.reprojection_error_pixels < 0.0:
        raise ValueError("reprojection_error_pixels must be non-negative")
    if observation.focal_length_pixels <= 0.0:
        raise ValueError("focal_length_pixels must be positive")
    if observation.alignment_position_rmse_metres < 0.0:
        raise ValueError("alignment_position_rmse_metres must be non-negative")
    if observation.alignment_orientation_error_degrees < 0.0:
        raise ValueError("alignment_orientation_error_degrees must be non-negative")
    if observation.alignment_orientation_error_degrees >= 89.0:
        raise ValueError("alignment orientation error must remain below 89 degrees")


def predict_uncertainty(
    observation: UncertaintyObservation,
    config: UncertaintyModelConfig = UncertaintyModelConfig(),
) -> UncertaintyPrediction:
    """Predict metric 1-sigma error from observable uncertainty sources.

    The v1 model assumes independent zero-mean error sources and therefore combines component
    standard deviations in quadrature. That independence assumption is itself an ablation target.
    """

    validate_config(config)
    validate_observation(observation)

    depth = observation.depth_metres
    base_sensor_sigma = (
        config.depth_noise_floor_metres
        + config.depth_noise_quadratic_metres_per_metre_squared * depth * depth
    )
    sensor_sigma = base_sensor_sigma * (
        1.0 + config.sensor_confidence_penalty * (1.0 - observation.sensor_confidence)
    )
    pose_translation_sigma = (
        config.pose_translation_floor_metres
        + config.pose_translation_scale_metres * (1.0 - observation.pose_confidence)
    )
    reprojection_sigma = (
        depth * observation.reprojection_error_pixels / observation.focal_length_pixels
    )
    alignment_position_sigma = observation.alignment_position_rmse_metres
    alignment_rotation_sigma = depth * math.tan(
        math.radians(observation.alignment_orientation_error_degrees)
    )

    variance = (
        sensor_sigma * sensor_sigma
        + pose_translation_sigma * pose_translation_sigma
        + reprojection_sigma * reprojection_sigma
        + alignment_position_sigma * alignment_position_sigma
        + alignment_rotation_sigma * alignment_rotation_sigma
    )
    sigma = math.sqrt(variance)
    sigma = min(config.maximum_sigma_metres, max(config.minimum_sigma_metres, sigma))
    variance = sigma * sigma

    raw_weight = (config.reference_sigma_metres / sigma) ** 2
    precision_weight = min(
        config.maximum_precision_weight,
        max(config.minimum_precision_weight, raw_weight),
    )

    return UncertaintyPrediction(
        sigma_metres=sigma,
        variance_metres_squared=variance,
        precision_weight=precision_weight,
        sensor_sigma_metres=sensor_sigma,
        pose_translation_sigma_metres=pose_translation_sigma,
        reprojection_sigma_metres=reprojection_sigma,
        alignment_position_sigma_metres=alignment_position_sigma,
        alignment_rotation_sigma_metres=alignment_rotation_sigma,
    )


def _observation_from_json(payload: dict) -> UncertaintyObservation:
    return UncertaintyObservation(
        depth_metres=float(payload["depthMetres"]),
        sensor_confidence=float(payload["sensorConfidence"]),
        pose_confidence=float(payload["poseConfidence"]),
        reprojection_error_pixels=float(payload["reprojectionErrorPixels"]),
        focal_length_pixels=float(payload["focalLengthPixels"]),
        alignment_position_rmse_metres=float(payload.get("alignmentPositionRmseMetres", 0.0)),
        alignment_orientation_error_degrees=float(
            payload.get("alignmentOrientationErrorDegrees", 0.0)
        ),
    )


def prediction_to_json(prediction: UncertaintyPrediction) -> dict:
    return {
        "predictedSigmaMetres": prediction.sigma_metres,
        "predictedVarianceMetresSquared": prediction.variance_metres_squared,
        "precisionWeight": prediction.precision_weight,
        "components": {
            "sensorSigmaMetres": prediction.sensor_sigma_metres,
            "poseTranslationSigmaMetres": prediction.pose_translation_sigma_metres,
            "reprojectionSigmaMetres": prediction.reprojection_sigma_metres,
            "alignmentPositionSigmaMetres": prediction.alignment_position_sigma_metres,
            "alignmentRotationSigmaMetres": prediction.alignment_rotation_sigma_metres,
        },
    }


def predict_jsonl(lines: Iterable[str], config: UncertaintyModelConfig) -> list[dict]:
    predictions = []
    for line_number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
            observation = _observation_from_json(payload)
            result = prediction_to_json(predict_uncertainty(observation, config))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid observation on line {line_number}: {exc}") from exc
        for key in ("scene", "method", "viewCount", "seed", "sampleId", "signedErrorMetres"):
            if key in payload:
                result[key] = payload[key]
        predictions.append(result)
    return predictions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSONL observations")
    parser.add_argument("--output", type=Path, required=True, help="prediction JSONL")
    args = parser.parse_args()

    predictions = predict_jsonl(args.input.read_text().splitlines(), UncertaintyModelConfig())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as stream:
        for prediction in predictions:
            stream.write(json.dumps(prediction, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
