#!/usr/bin/env python3
"""Fit Maveb metric-uncertainty coefficients with a fixed Student-t(3) calibration likelihood.

This is the preregistered U1b amendment after the original single-Gaussian calibration model was
shown, on calibration data only, to saturate both depth-noise search bounds and the 0.25 m sigma cap
because the empirical ARKit-vs-FARO residual distribution has a small but extreme heavy tail.

The amendment changes only the residual likelihood. It keeps the exact frozen split, deterministic
scene-balanced sample selection, fitted coefficients (a, b, k), parameter bounds, six coordinate
rounds, 48 golden-section iterations, and all observations. No sample is rejected or trimmed.

The model's ``sigma`` remains a standard deviation. For Student-t degrees of freedom nu > 2, the
likelihood scale is therefore ``sigma * sqrt((nu - 2) / nu)`` so the predictive variance remains
``sigma**2`` and downstream inverse-variance weighting retains its original interpretation.
"""

from __future__ import annotations

from dataclasses import replace
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

import geometric_uncertainty as uncertainty
import fit_metric_uncertainty as gaussian_fit


DEFAULT_DF = 3.0


def student_t_nll_array(errors: np.ndarray, sigma: np.ndarray, degrees_of_freedom: float) -> np.ndarray:
    """Student-t negative log likelihood with ``sigma`` parameterized as standard deviation."""

    nu = float(degrees_of_freedom)
    if not math.isfinite(nu) or nu <= 2.0:
        raise ValueError("Student-t degrees of freedom must be finite and > 2")
    if np.any(~np.isfinite(sigma)) or np.any(sigma <= 0.0):
        raise ValueError("Student-t sigma must be finite and positive")

    scale = sigma * math.sqrt((nu - 2.0) / nu)
    standardized = errors / scale
    constant = (
        0.5 * math.log(nu * math.pi)
        + math.lgamma(nu / 2.0)
        - math.lgamma((nu + 1.0) / 2.0)
    )
    return (
        np.log(scale)
        + constant
        + 0.5 * (nu + 1.0) * np.log1p((standardized * standardized) / nu)
    )


def vectorized_student_t_scene_balanced_objective(
    arrays: gaussian_fit.CalibrationArrays,
    config: uncertainty.UncertaintyModelConfig,
    *,
    degrees_of_freedom: float = DEFAULT_DF,
) -> tuple[float, dict[str, float]]:
    """Exact scene-balanced Student-t objective for the same v1 sigma model."""

    uncertainty.validate_config(config)
    base_sensor_sigma = (
        config.depth_noise_floor_metres
        + config.depth_noise_quadratic_metres_per_metre_squared * arrays.depth_squared
    )
    sensor_sigma = base_sensor_sigma * (
        1.0 + config.sensor_confidence_penalty * arrays.confidence_deficit
    )
    sigma = np.sqrt(sensor_sigma * sensor_sigma + arrays.fixed_variance)
    sigma = np.clip(sigma, config.minimum_sigma_metres, config.maximum_sigma_metres)
    nll = student_t_nll_array(arrays.signed_error, sigma, degrees_of_freedom)

    objective = float(np.dot(arrays.sample_weights, nll))
    scene_sums = np.bincount(
        arrays.scene_index,
        weights=nll,
        minlength=len(arrays.scene_names),
    )
    per_scene = {
        scene: float(scene_sums[index] / arrays.scene_counts[index])
        for index, scene in enumerate(arrays.scene_names)
    }
    return objective, per_scene


def fit_sensor_terms_student_t(
    samples,
    initial: uncertainty.UncertaintyModelConfig = uncertainty.UncertaintyModelConfig(),
    *,
    rounds: int = 6,
    arrays: gaussian_fit.CalibrationArrays | None = None,
    degrees_of_freedom: float = DEFAULT_DF,
) -> tuple[uncertainty.UncertaintyModelConfig, list[dict]]:
    """Fit the same a/b/k sensor terms under a fixed robust Student-t likelihood."""

    if rounds <= 0:
        raise ValueError("rounds must be positive")
    if not math.isfinite(degrees_of_freedom) or degrees_of_freedom <= 2.0:
        raise ValueError("Student-t degrees of freedom must be finite and > 2")
    if arrays is None:
        arrays = gaussian_fit.calibration_arrays(samples, initial)

    config = initial
    trace = []
    parameter_specs = (
        ("depth_noise_floor_metres", 1.0e-5, 0.10),
        ("depth_noise_quadratic_metres_per_metre_squared", 0.0, 0.05),
        ("sensor_confidence_penalty", 0.0, 20.0),
    )

    for round_index in range(rounds):
        for field, lower, upper in parameter_specs:
            def scalar_objective(value: float) -> float:
                candidate = replace(config, **{field: value})
                return vectorized_student_t_scene_balanced_objective(
                    arrays,
                    candidate,
                    degrees_of_freedom=degrees_of_freedom,
                )[0]

            best_value, best_objective = gaussian_fit._golden_section_minimize(
                scalar_objective,
                lower,
                upper,
            )
            config = replace(config, **{field: best_value})
            record = {
                "round": round_index,
                "parameter": field,
                "value": best_value,
                "sceneBalancedStudentTNll": best_objective,
            }
            trace.append(record)
            print(
                json.dumps({"fitProgress": record}, sort_keys=True),
                file=sys.stderr,
                flush=True,
            )

    uncertainty.validate_config(config)
    return config, trace


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="raw uncertainty observation JSONL")
    parser.add_argument("--split", type=Path, required=True, help="frozen calibration/held-out split")
    parser.add_argument("--output", type=Path, required=True, help="robust fitted model JSON")
    parser.add_argument("--max-per-scene", type=int, default=100_000)
    parser.add_argument("--sample-seed", type=int, default=42)
    parser.add_argument("--rounds", type=int, default=6)
    parser.add_argument("--degrees-of-freedom", type=float, default=DEFAULT_DF)
    args = parser.parse_args()

    try:
        input_bytes = args.input.read_bytes()
        split_bytes = args.split.read_bytes()
        all_samples = gaussian_fit.parse_jsonl(input_bytes.decode("utf-8").splitlines())
        calibration_scenes, split_payload = gaussian_fit.load_scene_split(args.split)
        samples = gaussian_fit.select_scenes(all_samples, calibration_scenes)
        samples = gaussian_fit.stable_scene_downsample(
            samples,
            args.max_per_scene,
            args.sample_seed,
        )
        initial = uncertainty.UncertaintyModelConfig()
        arrays = gaussian_fit.calibration_arrays(samples, initial)
        before, before_by_scene = vectorized_student_t_scene_balanced_objective(
            arrays,
            initial,
            degrees_of_freedom=args.degrees_of_freedom,
        )
        fitted, trace = fit_sensor_terms_student_t(
            samples,
            initial,
            rounds=args.rounds,
            arrays=arrays,
            degrees_of_freedom=args.degrees_of_freedom,
        )
        after, after_by_scene = vectorized_student_t_scene_balanced_objective(
            arrays,
            fitted,
            degrees_of_freedom=args.degrees_of_freedom,
        )
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"fit_metric_uncertainty_student_t: {exc}")
        return 2

    counts: dict[str, int] = {}
    for sample in samples:
        counts[sample.scene] = counts.get(sample.scene, 0) + 1

    report = {
        "schemaVersion": 1,
        "modelId": "metric-uncertainty-v1-student-t3",
        "status": "fitted-robust-calibration-only-not-held-out-validated",
        "amendmentReason": (
            "single-Gaussian U1 saturated both depth-noise upper bounds and the 0.25 m sigma cap "
            "on calibration-only data; Student-t(3) retains all samples while modeling the heavy tail"
        ),
        "inputSha256": hashlib.sha256(input_bytes).hexdigest(),
        "splitSha256": hashlib.sha256(split_bytes).hexdigest(),
        "splitId": split_payload.get("id", "unknown"),
        "splitRevision": split_payload.get("revision"),
        "calibrationScenes": calibration_scenes,
        "samplesPerScene": dict(sorted(counts.items())),
        "sampleSelection": {
            "method": "stable-sha256-rank-per-scene",
            "maximumPerScene": args.max_per_scene,
            "seed": args.sample_seed,
        },
        "likelihood": {
            "family": "Student-t",
            "degreesOfFreedom": args.degrees_of_freedom,
            "degreesOfFreedomFitted": False,
            "sigmaInterpretation": "standard deviation",
            "likelihoodScale": "sigma * sqrt((nu - 2) / nu)",
            "sampleFiltering": "none",
        },
        "optimizer": {
            "objective": "mean-per-scene-student-t-nll",
            "implementation": "numpy-vectorized-exact-v1",
            "coordinateRounds": args.rounds,
            "goldenSectionIterationsPerCoordinate": 48,
            "parameterBoundsUnchangedFromGaussianU1": True,
        },
        "fittedTerms": [
            "depthNoiseFloorMetres",
            "depthNoiseQuadraticMetresPerMetreSquared",
            "sensorConfidencePenalty",
        ],
        "frozenTerms": [
            "poseTranslationFloorMetres",
            "poseTranslationScaleMetres",
            "alignment terms are observation inputs, not fitted coefficients in public U1",
        ],
        "objective": {
            "name": "mean-per-scene-student-t-nll",
            "before": before,
            "after": after,
            "beforeByScene": before_by_scene,
            "afterByScene": after_by_scene,
        },
        "boundaryFlags": {
            "depthNoiseFloorAtUpperBound": fitted.depth_noise_floor_metres >= 0.099999,
            "depthNoiseQuadraticAtUpperBound": (
                fitted.depth_noise_quadratic_metres_per_metre_squared >= 0.049999
            ),
            "sensorConfidencePenaltyAtUpperBound": fitted.sensor_confidence_penalty >= 19.999,
        },
        "modelConfig": uncertainty.config_to_json(fitted),
        "optimizationTrace": trace,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "ok": True,
                "output": str(args.output.resolve()),
                "objectiveBefore": before,
                "objectiveAfter": after,
                "boundaryFlags": report["boundaryFlags"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
