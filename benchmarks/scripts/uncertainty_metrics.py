#!/usr/bin/env python3
"""Evaluate calibration and usefulness of predicted metric geometric uncertainty."""

from __future__ import annotations

from dataclasses import dataclass
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
from typing import Iterable, Sequence


@dataclass(frozen=True)
class ErrorSample:
    predicted_sigma_metres: float
    signed_error_metres: float
    scene: str = "unknown"
    method: str = "unknown"
    view_count: int = 0
    seed: int = 0


def _validate_sample(sample: ErrorSample) -> None:
    if not math.isfinite(sample.predicted_sigma_metres) or sample.predicted_sigma_metres <= 0.0:
        raise ValueError("predicted sigma must be finite and positive")
    if not math.isfinite(sample.signed_error_metres):
        raise ValueError("signed error must be finite")
    if sample.view_count < 0:
        raise ValueError("view count must be non-negative")


def _validate_student_t_df(degrees_of_freedom: float | None) -> None:
    if degrees_of_freedom is None:
        return
    if not math.isfinite(degrees_of_freedom) or degrees_of_freedom <= 2.0:
        raise ValueError("Student-t degrees of freedom must be finite and > 2")


def parse_jsonl(lines: Iterable[str]) -> list[ErrorSample]:
    samples = []
    for line_number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
            sample = ErrorSample(
                predicted_sigma_metres=float(payload["predictedSigmaMetres"]),
                signed_error_metres=float(payload["signedErrorMetres"]),
                scene=str(payload.get("scene", "unknown")),
                method=str(payload.get("method", "unknown")),
                view_count=int(payload.get("viewCount", 0)),
                seed=int(payload.get("seed", 0)),
            )
            _validate_sample(sample)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid uncertainty sample on line {line_number}: {exc}") from exc
        samples.append(sample)
    if not samples:
        raise ValueError("uncertainty evaluation requires at least one sample")
    return samples


def _pearson_sigma_absolute_error(samples: Sequence[ErrorSample]) -> float | None:
    sigmas = [sample.predicted_sigma_metres for sample in samples]
    errors = [abs(sample.signed_error_metres) for sample in samples]
    mean_sigma = sum(sigmas) / len(sigmas)
    mean_error = sum(errors) / len(errors)
    numerator = sum(
        (sigma - mean_sigma) * (error - mean_error)
        for sigma, error in zip(sigmas, errors)
    )
    sigma_energy = sum((sigma - mean_sigma) ** 2 for sigma in sigmas)
    error_energy = sum((error - mean_error) ** 2 for error in errors)
    denominator = math.sqrt(sigma_energy * error_energy)
    if denominator <= 1.0e-18:
        return None
    return numerator / denominator


def student_t_nll(sample: ErrorSample, degrees_of_freedom: float) -> float:
    """Student-t NLL with predicted sigma interpreted as standard deviation."""

    _validate_student_t_df(degrees_of_freedom)
    nu = float(degrees_of_freedom)
    scale = sample.predicted_sigma_metres * math.sqrt((nu - 2.0) / nu)
    normalized_squared = (sample.signed_error_metres / scale) ** 2
    return (
        math.log(scale)
        + 0.5 * math.log(nu * math.pi)
        + math.lgamma(nu / 2.0)
        - math.lgamma((nu + 1.0) / 2.0)
        + 0.5 * (nu + 1.0) * math.log1p(normalized_squared / nu)
    )


def calibration_bins(samples: Sequence[ErrorSample], bin_count: int) -> list[dict]:
    if bin_count <= 0:
        raise ValueError("bin count must be positive")
    ordered = sorted(samples, key=lambda sample: sample.predicted_sigma_metres)
    actual_bins = min(bin_count, len(ordered))
    bins = []
    for index in range(actual_bins):
        start = index * len(ordered) // actual_bins
        end = (index + 1) * len(ordered) // actual_bins
        bucket = ordered[start:end]
        predicted_rms = math.sqrt(
            sum(sample.predicted_sigma_metres**2 for sample in bucket) / len(bucket)
        )
        empirical_rmse = math.sqrt(
            sum(sample.signed_error_metres**2 for sample in bucket) / len(bucket)
        )
        bins.append(
            {
                "count": len(bucket),
                "minimumSigmaMetres": bucket[0].predicted_sigma_metres,
                "maximumSigmaMetres": bucket[-1].predicted_sigma_metres,
                "predictedRmsSigmaMetres": predicted_rms,
                "empiricalRmseMetres": empirical_rmse,
                "absoluteCalibrationGapMetres": abs(predicted_rms - empirical_rmse),
            }
        )
    return bins


def evaluate(
    samples: Sequence[ErrorSample],
    bin_count: int = 10,
    student_t_df: float | None = None,
) -> dict:
    if not samples:
        raise ValueError("uncertainty evaluation requires at least one sample")
    _validate_student_t_df(student_t_df)
    for sample in samples:
        _validate_sample(sample)

    count = len(samples)
    squared_errors = [sample.signed_error_metres**2 for sample in samples]
    squared_sigmas = [sample.predicted_sigma_metres**2 for sample in samples]
    rmse = math.sqrt(sum(squared_errors) / count)
    sharpness = math.sqrt(sum(squared_sigmas) / count)
    gaussian_nll = sum(
        math.log(sample.predicted_sigma_metres)
        + 0.5 * (sample.signed_error_metres / sample.predicted_sigma_metres) ** 2
        + 0.5 * math.log(2.0 * math.pi)
        for sample in samples
    ) / count
    bins = calibration_bins(samples, bin_count)
    calibration_error = sum(
        bucket["count"] * bucket["absoluteCalibrationGapMetres"] for bucket in bins
    ) / count
    coverage_1 = sum(
        abs(sample.signed_error_metres) <= sample.predicted_sigma_metres for sample in samples
    ) / count
    coverage_2 = sum(
        abs(sample.signed_error_metres) <= 2.0 * sample.predicted_sigma_metres
        for sample in samples
    ) / count

    result = {
        "count": count,
        "empiricalRmseMetres": rmse,
        "sharpnessRmsSigmaMetres": sharpness,
        "gaussianNll": gaussian_nll,
        "expectedCalibrationErrorMetres": calibration_error,
        "coverage1Sigma": coverage_1,
        "coverage2Sigma": coverage_2,
        "pearsonSigmaAbsoluteError": _pearson_sigma_absolute_error(samples),
        "bins": bins,
    }
    if student_t_df is not None:
        result["studentTNll"] = sum(
            student_t_nll(sample, student_t_df) for sample in samples
        ) / count
        result["studentTDegreesOfFreedom"] = float(student_t_df)
    return result


def _metric_vector(metrics: dict) -> dict[str, float]:
    result = {
        "empiricalRmseMetres": metrics["empiricalRmseMetres"],
        "sharpnessRmsSigmaMetres": metrics["sharpnessRmsSigmaMetres"],
        "gaussianNll": metrics["gaussianNll"],
        "expectedCalibrationErrorMetres": metrics["expectedCalibrationErrorMetres"],
        "coverage1Sigma": metrics["coverage1Sigma"],
        "coverage2Sigma": metrics["coverage2Sigma"],
    }
    if "studentTNll" in metrics:
        result["studentTNll"] = metrics["studentTNll"]
    correlation = metrics["pearsonSigmaAbsoluteError"]
    if correlation is not None:
        result["pearsonSigmaAbsoluteError"] = correlation
    return result


def bootstrap_intervals(
    samples: Sequence[ErrorSample],
    *,
    bin_count: int = 10,
    replicates: int = 0,
    seed: int = 42,
    student_t_df: float | None = None,
) -> dict[str, dict[str, float]]:
    if replicates < 0:
        raise ValueError("bootstrap replicates must be non-negative")
    _validate_student_t_df(student_t_df)
    if replicates == 0:
        return {}
    rng = random.Random(seed)
    distributions: dict[str, list[float]] = {}
    for _ in range(replicates):
        draw = [samples[rng.randrange(len(samples))] for _ in samples]
        for key, value in _metric_vector(evaluate(draw, bin_count, student_t_df)).items():
            distributions.setdefault(key, []).append(value)

    intervals = {}
    for key, values in distributions.items():
        values.sort()
        lower_index = max(0, math.floor(0.025 * (len(values) - 1)))
        upper_index = min(len(values) - 1, math.ceil(0.975 * (len(values) - 1)))
        intervals[key] = {
            "lower95": values[lower_index],
            "upper95": values[upper_index],
        }
    return intervals


def grouped_evaluation(
    samples: Sequence[ErrorSample],
    *,
    group_fields: Sequence[str] = ("method", "scene", "view_count"),
    bin_count: int = 10,
    bootstrap_replicates: int = 0,
    bootstrap_seed: int = 42,
    student_t_df: float | None = None,
) -> list[dict]:
    allowed = {"method", "scene", "view_count", "seed"}
    if any(field not in allowed for field in group_fields):
        raise ValueError(f"group fields must be drawn from {sorted(allowed)}")
    _validate_student_t_df(student_t_df)
    groups: dict[tuple, list[ErrorSample]] = {}
    for sample in samples:
        key = tuple(getattr(sample, field) for field in group_fields)
        groups.setdefault(key, []).append(sample)

    results = []
    for key in sorted(groups, key=lambda item: tuple(str(value) for value in item)):
        group_samples = groups[key]
        metrics = evaluate(group_samples, bin_count, student_t_df)
        results.append(
            {
                "group": {
                    ("viewCount" if field == "view_count" else field): value
                    for field, value in zip(group_fields, key)
                },
                "metrics": metrics,
                "bootstrap95": bootstrap_intervals(
                    group_samples,
                    bin_count=bin_count,
                    replicates=bootstrap_replicates,
                    seed=bootstrap_seed,
                    student_t_df=student_t_df,
                ),
            }
        )
    return results


def render_markdown(groups: Sequence[dict]) -> str:
    lines = [
        "# Metric uncertainty calibration",
        "",
        "| Method | Scene | Views | N | RMSE (m) | ECE (m) | Gaussian NLL | Student-t NLL | 1sigma cov. | 2sigma cov. | sigma<->|e| r |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for record in groups:
        group = record["group"]
        metrics = record["metrics"]
        correlation = metrics["pearsonSigmaAbsoluteError"]
        correlation_text = "n/a" if correlation is None else f"{correlation:.4f}"
        student_t_text = "n/a" if "studentTNll" not in metrics else f"{metrics['studentTNll']:.6f}"
        lines.append(
            "| {method} | {scene} | {views} | {count} | {rmse:.6f} | {ece:.6f} | "
            "{gnll:.6f} | {tnll} | {c1:.3f} | {c2:.3f} | {corr} |".format(
                method=group.get("method", "all"),
                scene=group.get("scene", "all"),
                views=group.get("viewCount", "all"),
                count=metrics["count"],
                rmse=metrics["empiricalRmseMetres"],
                ece=metrics["expectedCalibrationErrorMetres"],
                gnll=metrics["gaussianNll"],
                tnll=student_t_text,
                c1=metrics["coverage1Sigma"],
                c2=metrics["coverage2Sigma"],
                corr=correlation_text,
            )
        )
    lines.append("")
    lines.append(
        "ECE is the count-weighted absolute gap between predicted RMS sigma and empirical "
        "RMSE in equal-count sigma bins. Student-t NLL is the primary proper score when a "
        "Student-t calibration model is supplied; Gaussian NLL is retained as a legacy diagnostic. "
        "When scene is a grouping field, pixel-level bootstrap is deliberately suppressed: paired "
        "scene bootstrap is performed by compare_uncertainty_controls.py."
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSONL with predictedSigmaMetres/signedErrorMetres")
    parser.add_argument("--output", type=Path, required=True, help="machine-readable JSON report")
    parser.add_argument("--markdown", type=Path, help="optional Markdown summary")
    parser.add_argument("--bins", type=int, default=10)
    parser.add_argument("--bootstrap", type=int, default=0)
    parser.add_argument("--bootstrap-seed", type=int, default=42)
    parser.add_argument("--student-t-df", type=float)
    parser.add_argument(
        "--group-by",
        default="method,scene,view_count",
        help="comma-separated subset of method,scene,view_count,seed",
    )
    args = parser.parse_args()

    _validate_student_t_df(args.student_t_df)
    input_bytes = args.input.read_bytes()
    samples = parse_jsonl(input_bytes.decode("utf-8").splitlines())
    group_fields = tuple(field.strip() for field in args.group_by.split(",") if field.strip())
    suppress_pixel_bootstrap = "scene" in group_fields and args.bootstrap > 0
    effective_bootstrap = 0 if suppress_pixel_bootstrap else args.bootstrap
    groups = grouped_evaluation(
        samples,
        group_fields=group_fields,
        bin_count=args.bins,
        bootstrap_replicates=effective_bootstrap,
        bootstrap_seed=args.bootstrap_seed,
        student_t_df=args.student_t_df,
    )
    report = {
        "schemaVersion": 2,
        "inputSha256": hashlib.sha256(input_bytes).hexdigest(),
        "binCount": args.bins,
        "bootstrapReplicatesRequested": args.bootstrap,
        "bootstrapReplicates": effective_bootstrap,
        "bootstrapSeed": args.bootstrap_seed,
        "pixelBootstrapSuppressedForSceneEvidence": suppress_pixel_bootstrap,
        "groupFields": list(group_fields),
        "studentTDegreesOfFreedom": args.student_t_df,
        "primaryProperScore": "studentTNll" if args.student_t_df is not None else "gaussianNll",
        "groups": groups,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(groups))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
