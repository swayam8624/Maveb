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


def evaluate(samples: Sequence[ErrorSample], bin_count: int = 10) -> dict:
    if not samples:
        raise ValueError("uncertainty evaluation requires at least one sample")
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

    return {
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


def _metric_vector(metrics: dict) -> dict[str, float]:
    result = {
        "empiricalRmseMetres": metrics["empiricalRmseMetres"],
        "sharpnessRmsSigmaMetres": metrics["sharpnessRmsSigmaMetres"],
        "gaussianNll": metrics["gaussianNll"],
        "expectedCalibrationErrorMetres": metrics["expectedCalibrationErrorMetres"],
        "coverage1Sigma": metrics["coverage1Sigma"],
        "coverage2Sigma": metrics["coverage2Sigma"],
    }
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
) -> dict[str, dict[str, float]]:
    if replicates < 0:
        raise ValueError("bootstrap replicates must be non-negative")
    if replicates == 0:
        return {}
    rng = random.Random(seed)
    distributions: dict[str, list[float]] = {}
    for _ in range(replicates):
        draw = [samples[rng.randrange(len(samples))] for _ in samples]
        for key, value in _metric_vector(evaluate(draw, bin_count)).items():
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
) -> list[dict]:
    allowed = {"method", "scene", "view_count", "seed"}
    if any(field not in allowed for field in group_fields):
        raise ValueError(f"group fields must be drawn from {sorted(allowed)}")
    groups: dict[tuple, list[ErrorSample]] = {}
    for sample in samples:
        key = tuple(getattr(sample, field) for field in group_fields)
        groups.setdefault(key, []).append(sample)

    results = []
    for key in sorted(groups, key=lambda item: tuple(str(value) for value in item)):
        group_samples = groups[key]
        metrics = evaluate(group_samples, bin_count)
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
                ),
            }
        )
    return results


def render_markdown(groups: Sequence[dict]) -> str:
    lines = [
        "# Metric uncertainty calibration",
        "",
        "| Method | Scene | Views | N | RMSE (m) | ECE (m) | 1sigma cov. | 2sigma cov. | sigma<->|e| r |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for record in groups:
        group = record["group"]
        metrics = record["metrics"]
        correlation = metrics["pearsonSigmaAbsoluteError"]
        correlation_text = "n/a" if correlation is None else f"{correlation:.4f}"
        lines.append(
            "| {method} | {scene} | {views} | {count} | {rmse:.6f} | {ece:.6f} | "
            "{c1:.3f} | {c2:.3f} | {corr} |".format(
                method=group.get("method", "all"),
                scene=group.get("scene", "all"),
                views=group.get("viewCount", "all"),
                count=metrics["count"],
                rmse=metrics["empiricalRmseMetres"],
                ece=metrics["expectedCalibrationErrorMetres"],
                c1=metrics["coverage1Sigma"],
                c2=metrics["coverage2Sigma"],
                corr=correlation_text,
            )
        )
    lines.append("")
    lines.append(
        "ECE is the count-weighted absolute gap between predicted RMS sigma and empirical "
        "RMSE in equal-count sigma bins. Scene-level summaries, not pooled pixels, are the "
        "unit of evidence for research claims."
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
    parser.add_argument(
        "--group-by",
        default="method,scene,view_count",
        help="comma-separated subset of method,scene,view_count,seed",
    )
    args = parser.parse_args()

    input_bytes = args.input.read_bytes()
    samples = parse_jsonl(input_bytes.decode("utf-8").splitlines())
    group_fields = tuple(field.strip() for field in args.group_by.split(",") if field.strip())
    groups = grouped_evaluation(
        samples,
        group_fields=group_fields,
        bin_count=args.bins,
        bootstrap_replicates=args.bootstrap,
        bootstrap_seed=args.bootstrap_seed,
    )
    report = {
        "schemaVersion": 1,
        "inputSha256": hashlib.sha256(input_bytes).hexdigest(),
        "binCount": args.bins,
        "bootstrapReplicates": args.bootstrap,
        "bootstrapSeed": args.bootstrap_seed,
        "groupFields": list(group_fields),
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
