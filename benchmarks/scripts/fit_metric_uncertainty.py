#!/usr/bin/env python3
"""Fit Maveb metric-uncertainty coefficients on an explicit calibration scene split.

The fitter is deliberately small, deterministic, and dependency-free. It minimizes the mean of
per-scene Gaussian negative log likelihoods so a scene with more pixels cannot dominate merely by
sample count. U1 initially fits only the ARKit sensor terms; pose/alignment terms remain frozen until
paired data exists to identify them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Callable, Iterable, Sequence

import geometric_uncertainty as uncertainty


@dataclass(frozen=True)
class CalibrationSample:
    observation: uncertainty.UncertaintyObservation
    signed_error_metres: float
    scene: str
    sample_id: str


def parse_jsonl(lines: Iterable[str]) -> list[CalibrationSample]:
    samples = []
    for line_number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
            observation = uncertainty.observation_from_json(payload)
            signed_error = float(payload["signedErrorMetres"])
            scene = str(payload["scene"])
            sample_id = str(payload.get("sampleId", f"line-{line_number}"))
            if not math.isfinite(signed_error):
                raise ValueError("signedErrorMetres must be finite")
            if not scene:
                raise ValueError("scene must be non-empty")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid calibration sample on line {line_number}: {exc}") from exc
        samples.append(CalibrationSample(observation, signed_error, scene, sample_id))
    if not samples:
        raise ValueError("calibration input contains no samples")
    return samples


def select_scenes(samples: Sequence[CalibrationSample], scenes: Sequence[str]) -> list[CalibrationSample]:
    requested = set(scenes)
    if not requested:
        raise ValueError("at least one calibration scene must be explicitly selected")
    available = {sample.scene for sample in samples}
    missing = sorted(requested - available)
    if missing:
        raise ValueError(f"calibration scenes are missing from input: {', '.join(missing)}")
    return [sample for sample in samples if sample.scene in requested]


def stable_scene_downsample(
    samples: Sequence[CalibrationSample], maximum_per_scene: int, seed: int
) -> list[CalibrationSample]:
    if maximum_per_scene <= 0:
        raise ValueError("maximum_per_scene must be positive")
    by_scene: dict[str, list[CalibrationSample]] = {}
    for sample in samples:
        by_scene.setdefault(sample.scene, []).append(sample)
    selected = []
    for scene in sorted(by_scene):
        ranked = sorted(
            by_scene[scene],
            key=lambda sample: hashlib.sha256(
                f"{seed}|{scene}|{sample.sample_id}".encode("utf-8")
            ).digest(),
        )
        selected.extend(ranked[:maximum_per_scene])
    return selected


def gaussian_nll(signed_error: float, sigma: float) -> float:
    if sigma <= 0.0 or not math.isfinite(sigma):
        return math.inf
    normalized = signed_error / sigma
    return math.log(sigma) + 0.5 * normalized * normalized + 0.5 * math.log(2.0 * math.pi)


def scene_balanced_objective(
    samples: Sequence[CalibrationSample], config: uncertainty.UncertaintyModelConfig
) -> tuple[float, dict[str, float]]:
    if not samples:
        raise ValueError("objective requires samples")
    per_scene_values: dict[str, list[float]] = {}
    for sample in samples:
        sigma = uncertainty.predict_uncertainty(sample.observation, config).sigma_metres
        per_scene_values.setdefault(sample.scene, []).append(gaussian_nll(sample.signed_error_metres, sigma))
    per_scene = {
        scene: sum(values) / len(values) for scene, values in sorted(per_scene_values.items())
    }
    return sum(per_scene.values()) / len(per_scene), per_scene


def _golden_section_minimize(
    objective: Callable[[float], float],
    lower: float,
    upper: float,
    *,
    iterations: int = 48,
) -> tuple[float, float]:
    if not (math.isfinite(lower) and math.isfinite(upper) and lower < upper):
        raise ValueError("invalid optimization interval")
    ratio = (math.sqrt(5.0) - 1.0) / 2.0
    left = upper - ratio * (upper - lower)
    right = lower + ratio * (upper - lower)
    f_left = objective(left)
    f_right = objective(right)
    for _ in range(iterations):
        if f_left <= f_right:
            upper = right
            right = left
            f_right = f_left
            left = upper - ratio * (upper - lower)
            f_left = objective(left)
        else:
            lower = left
            left = right
            f_left = f_right
            right = lower + ratio * (upper - lower)
            f_right = objective(right)
    return (left, f_left) if f_left <= f_right else (right, f_right)


def fit_sensor_terms(
    samples: Sequence[CalibrationSample],
    initial: uncertainty.UncertaintyModelConfig = uncertainty.UncertaintyModelConfig(),
    *,
    rounds: int = 6,
) -> tuple[uncertainty.UncertaintyModelConfig, list[dict]]:
    """Fit depth floor, quadratic depth term, and confidence penalty only.

    U1 ARKitScenes has trusted recorded poses and no cross-sensor alignment residual, so fitting pose
    or alignment coefficients here would be unidentifiable. Those terms remain frozen by design.
    """

    if rounds <= 0:
        raise ValueError("rounds must be positive")
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
                return scene_balanced_objective(samples, candidate)[0]

            best_value, best_objective = _golden_section_minimize(
                scalar_objective, lower, upper
            )
            config = replace(config, **{field: best_value})
            trace.append(
                {
                    "round": round_index,
                    "parameter": field,
                    "value": best_value,
                    "sceneBalancedGaussianNll": best_objective,
                }
            )
    uncertainty.validate_config(config)
    return config, trace


def load_scene_split(path: Path) -> tuple[list[str], dict]:
    payload = json.loads(path.read_text())
    if payload.get("schemaVersion") != 1:
        raise ValueError("unsupported uncertainty split schema")
    calibration = payload.get("calibrationScenes")
    held_out = payload.get("heldOutScenes")
    if not isinstance(calibration, list) or not isinstance(held_out, list):
        raise ValueError("split must contain calibrationScenes and heldOutScenes arrays")
    calibration = [str(scene) for scene in calibration]
    held_out = [str(scene) for scene in held_out]
    overlap = sorted(set(calibration) & set(held_out))
    if overlap:
        raise ValueError(f"calibration/held-out leakage: {', '.join(overlap)}")
    if len(set(calibration)) != len(calibration) or len(set(held_out)) != len(held_out):
        raise ValueError("scene split contains duplicates")
    if not calibration:
        raise ValueError("calibrationScenes is empty; populate and freeze the split first")
    return calibration, payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="raw uncertainty observation JSONL")
    parser.add_argument("--split", type=Path, required=True, help="frozen calibration/held-out split")
    parser.add_argument("--output", type=Path, required=True, help="fitted model JSON")
    parser.add_argument("--max-per-scene", type=int, default=100_000)
    parser.add_argument("--sample-seed", type=int, default=42)
    parser.add_argument("--rounds", type=int, default=6)
    args = parser.parse_args()

    try:
        input_bytes = args.input.read_bytes()
        split_bytes = args.split.read_bytes()
        all_samples = parse_jsonl(input_bytes.decode("utf-8").splitlines())
        calibration_scenes, split_payload = load_scene_split(args.split)
        samples = select_scenes(all_samples, calibration_scenes)
        samples = stable_scene_downsample(samples, args.max_per_scene, args.sample_seed)
        initial = uncertainty.UncertaintyModelConfig()
        before, before_by_scene = scene_balanced_objective(samples, initial)
        fitted, trace = fit_sensor_terms(samples, initial, rounds=args.rounds)
        after, after_by_scene = scene_balanced_objective(samples, fitted)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"fit_metric_uncertainty: {exc}")
        return 2

    counts: dict[str, int] = {}
    for sample in samples:
        counts[sample.scene] = counts.get(sample.scene, 0) + 1
    report = {
        "schemaVersion": 1,
        "modelId": "metric-uncertainty-v1",
        "status": "fitted-calibration-only-not-held-out-validated",
        "inputSha256": hashlib.sha256(input_bytes).hexdigest(),
        "splitSha256": hashlib.sha256(split_bytes).hexdigest(),
        "splitId": split_payload.get("id", "unknown"),
        "calibrationScenes": calibration_scenes,
        "samplesPerScene": dict(sorted(counts.items())),
        "sampleSelection": {
            "method": "stable-sha256-rank-per-scene",
            "maximumPerScene": args.max_per_scene,
            "seed": args.sample_seed,
        },
        "fittedTerms": [
            "depthNoiseFloorMetres",
            "depthNoiseQuadraticMetresPerMetreSquared",
            "sensorConfidencePenalty",
        ],
        "frozenTerms": [
            "poseTranslationFloorMetres",
            "poseTranslationScaleMetres",
            "alignment terms are observation inputs, not fitted coefficients in v1",
        ],
        "objective": {
            "name": "mean-per-scene-gaussian-nll",
            "before": before,
            "after": after,
            "beforeByScene": before_by_scene,
            "afterByScene": after_by_scene,
        },
        "modelConfig": uncertainty.config_to_json(fitted),
        "optimizationTrace": trace,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"ok": True, "output": str(args.output.resolve()), "objectiveBefore": before, "objectiveAfter": after}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
