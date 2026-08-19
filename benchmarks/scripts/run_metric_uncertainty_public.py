#!/usr/bin/env python3
"""Run Maveb's frozen CA-1M metric-uncertainty public study.

Stages:
  prepare   Extract ARKit-LiDAR vs FARO-depth observations from the frozen CA-1M archives.
  fit       Fit sensor-only uncertainty coefficients on calibration scenes and freeze hashes.
  evaluate  Run intact/constant/shuffled controls on held-out scenes without retuning.
  all       prepare + fit + evaluate.

The runner never downloads data and never modifies the frozen split.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], *, cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def load_split(path: Path) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    payload = json.loads(raw)
    if payload.get("schemaVersion") != 1 or payload.get("frozen") is not True:
        raise ValueError("study requires the frozen schema-v1 public split")
    if payload.get("source", {}).get("dataset") != "CA-1M / Cubify Anything":
        raise ValueError("study requires the CA-1M FARO-ground-truth split")
    calibration = [str(v) for v in payload.get("calibrationScenes", [])]
    held_out = [str(v) for v in payload.get("heldOutScenes", [])]
    if len(calibration) < 3 or len(held_out) < 5 or set(calibration) & set(held_out):
        raise ValueError("public split does not satisfy 3-calibration / 5-held-out isolation")
    return payload, raw


def archive_path(data_root: Path, entry: dict) -> Path:
    return data_root / f"ca1m-{entry['ca1mSplit']}-{entry['videoId']}.tar"


def scene_paths(output_root: Path, scene: str) -> dict[str, Path]:
    root = output_root / "scenes" / scene
    return {
        "root": root,
        "samples": root / "observations.jsonl",
        "sample_meta": root / "observations.jsonl.meta.json",
    }


def concatenate_jsonl(inputs: list[Path], output: Path) -> int:
    count = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as destination:
        for path in inputs:
            with path.open("r", encoding="utf-8") as source:
                for line in source:
                    if line.strip():
                        destination.write(line)
                        count += 1
    if count == 0:
        raise ValueError(f"combined JSONL is empty: {output}")
    return count


def annotate_method(input_path: Path, output_path: Path, method: str) -> int:
    count = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with input_path.open("r", encoding="utf-8") as source, output_path.open(
        "w", encoding="utf-8"
    ) as destination:
        for line_number, raw in enumerate(source, start=1):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL line {line_number}: {input_path}") from exc
            row["method"] = method
            destination.write(json.dumps(row, sort_keys=True) + "\n")
            count += 1
    if count == 0:
        raise ValueError(f"annotated JSONL is empty: {input_path}")
    return count


def prepare(
    *,
    repo_root: Path,
    data_root: Path,
    output_root: Path,
    split: dict,
    frame_stride: int,
    pixel_stride: int,
    maximum_samples: int,
) -> list[dict]:
    sampler = repo_root / "benchmarks/scripts/ca1m_uncertainty_samples.py"
    prepared = []
    for scene in split["calibrationScenes"] + split["heldOutScenes"]:
        entry = split["sceneMetadata"][scene]
        archive = archive_path(data_root, entry)
        if not archive.is_file():
            raise ValueError(f"missing frozen CA-1M archive for {scene}: {archive}")
        paths = scene_paths(output_root, scene)
        run(
            [
                sys.executable,
                str(sampler),
                str(archive),
                "--scene",
                scene,
                "--video-id",
                str(entry["videoId"]),
                "--output",
                str(paths["samples"]),
                "--frame-stride",
                str(frame_stride),
                "--pixel-stride",
                str(pixel_stride),
                "--max-samples",
                str(maximum_samples),
            ],
            cwd=repo_root,
        )
        meta = json.loads(paths["sample_meta"].read_text())
        prepared.append(
            {
                "scene": scene,
                "role": entry["role"],
                "ca1mSplit": entry["ca1mSplit"],
                "videoId": entry["videoId"],
                "visitId": entry["visitId"],
                "archive": str(archive.resolve()),
                "archiveSha256": meta["archiveSha256"],
                "samples": str(paths["samples"].resolve()),
                "sampleSha256": meta["outputSha256"],
                "emittedSamples": meta["emittedSamples"],
                "completeFrames": meta["completeFrames"],
                "selectedFrames": meta["selectedFrames"],
            }
        )
    ledger = output_root / "prepare-ledger.json"
    ledger.write_text(json.dumps({"schemaVersion": 1, "scenes": prepared}, indent=2, sort_keys=True) + "\n")
    return prepared


def fit(
    *,
    repo_root: Path,
    output_root: Path,
    split_path: Path,
    split: dict,
    max_per_scene: int,
) -> Path:
    calibration_raw = output_root / "calibration/observations.jsonl"
    concatenate_jsonl(
        [scene_paths(output_root, scene)["samples"] for scene in split["calibrationScenes"]],
        calibration_raw,
    )
    fitted = output_root / "calibration/fitted-model.json"
    fitter = repo_root / "benchmarks/scripts/fit_metric_uncertainty.py"
    run(
        [
            sys.executable,
            str(fitter),
            str(calibration_raw),
            "--split",
            str(split_path),
            "--output",
            str(fitted),
            "--max-per-scene",
            str(max_per_scene),
        ],
        cwd=repo_root,
    )
    payload = json.loads(fitted.read_text())
    if payload.get("status") != "fitted-calibration-only-not-held-out-validated":
        raise ValueError("fitter did not produce a calibration-only model")
    if payload.get("splitSha256") != sha256_file(split_path):
        raise ValueError("fitted model split hash does not match the frozen CA-1M split")
    return fitted


def evaluate(
    *,
    repo_root: Path,
    output_root: Path,
    split: dict,
    fitted_model: Path,
    bootstrap: int,
    seed: int,
) -> dict:
    held_raw = output_root / "held-out/observations.jsonl"
    concatenate_jsonl(
        [scene_paths(output_root, scene)["samples"] for scene in split["heldOutScenes"]],
        held_raw,
    )
    controls = repo_root / "benchmarks/scripts/uncertainty_controls.py"
    predictor = repo_root / "benchmarks/scripts/geometric_uncertainty.py"
    metrics = repo_root / "benchmarks/scripts/uncertainty_metrics.py"
    reports = {}
    for mode, method in (
        ("intact", "u2-ca1m-intact-confidence"),
        ("constant", "u2-ca1m-constant-confidence"),
        ("shuffled", "u2-ca1m-shuffled-confidence"),
    ):
        root = output_root / "held-out" / mode
        controlled = root / "controlled.jsonl"
        annotated = root / "controlled-method.jsonl"
        predictions = root / "predictions.jsonl"
        report = root / "calibration-report.json"
        markdown = root / "calibration-report.md"
        run(
            [
                sys.executable,
                str(controls),
                str(held_raw),
                "--output",
                str(controlled),
                "--mode",
                mode,
                "--seed",
                str(seed),
                "--constant",
                "0.5",
            ],
            cwd=repo_root,
        )
        annotate_method(controlled, annotated, method)
        run(
            [
                sys.executable,
                str(predictor),
                str(annotated),
                "--output",
                str(predictions),
                "--config",
                str(fitted_model),
            ],
            cwd=repo_root,
        )
        run(
            [
                sys.executable,
                str(metrics),
                str(predictions),
                "--output",
                str(report),
                "--markdown",
                str(markdown),
                "--group-by",
                "method,scene",
                "--bootstrap",
                str(bootstrap),
                "--bootstrap-seed",
                str(seed),
            ],
            cwd=repo_root,
        )
        reports[mode] = {
            "method": method,
            "predictionsSha256": sha256_file(predictions),
            "report": str(report.resolve()),
            "reportSha256": sha256_file(report),
        }
    return reports


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("prepare", "fit", "evaluate", "all"), default="all")
    parser.add_argument(
        "--split",
        type=Path,
        default=repo_root / "benchmarks/experiments/metric-uncertainty-public-split-v1.json",
    )
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--frame-stride", type=int, default=10)
    parser.add_argument("--pixel-stride", type=int, default=4)
    parser.add_argument("--max-samples", type=int, default=500_000)
    parser.add_argument("--max-per-scene", type=int, default=100_000)
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    try:
        split_path = args.split.resolve()
        split, split_bytes = load_split(split_path)
        data_root = args.data_root.resolve()
        output_root = args.output_root.resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        results: dict = {}
        if args.stage in ("prepare", "all"):
            results["prepare"] = prepare(
                repo_root=repo_root,
                data_root=data_root,
                output_root=output_root,
                split=split,
                frame_stride=args.frame_stride,
                pixel_stride=args.pixel_stride,
                maximum_samples=args.max_samples,
            )
        fitted = output_root / "calibration/fitted-model.json"
        if args.stage in ("fit", "all"):
            fitted = fit(
                repo_root=repo_root,
                output_root=output_root,
                split_path=split_path,
                split=split,
                max_per_scene=args.max_per_scene,
            )
            results["fit"] = {"model": str(fitted.resolve()), "modelSha256": sha256_file(fitted)}
        if args.stage in ("evaluate", "all"):
            if not fitted.is_file():
                raise ValueError("held-out evaluation requires calibration/fitted-model.json")
            model_payload = json.loads(fitted.read_text())
            if model_payload.get("splitSha256") != hashlib.sha256(split_bytes).hexdigest():
                raise ValueError("held-out evaluation refuses a model fitted on another split")
            results["evaluate"] = evaluate(
                repo_root=repo_root,
                output_root=output_root,
                split=split,
                fitted_model=fitted,
                bootstrap=args.bootstrap,
                seed=args.seed,
            )
        ledger = {
            "schemaVersion": 1,
            "study": "metric-uncertainty-v1",
            "evidenceSource": "CA-1M onboard ARKit LiDAR vs FARO rendered GT depth",
            "stage": args.stage,
            "splitId": split["id"],
            "splitRevision": split.get("revision"),
            "splitSha256": hashlib.sha256(split_bytes).hexdigest(),
            "dataRoot": str(data_root),
            "outputRoot": str(output_root),
            "results": results,
        }
        ledger_path = output_root / "study-ledger.json"
        ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"ok": True, "ledger": str(ledger_path.resolve())}, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"run_metric_uncertainty_public: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
