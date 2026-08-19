#!/usr/bin/env python3
"""Run Maveb's frozen ARKitScenes metric-uncertainty public study.

Stages:
  prepare  Convert selected raw scenes and ray-sample signed depth error against reference meshes.
  fit      Fit sensor-only uncertainty coefficients on calibration scenes and freeze hashes.
  evaluate Run intact/constant/shuffled controls on held-out scenes and emit per-scene reports.
  all      prepare + fit + evaluate.

The runner never downloads data. Use acquire_arkit_uncertainty.py first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Iterable


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
    calibration = [str(v) for v in payload.get("calibrationScenes", [])]
    held_out = [str(v) for v in payload.get("heldOutScenes", [])]
    if len(calibration) < 3 or len(held_out) < 5 or set(calibration) & set(held_out):
        raise ValueError("public split does not satisfy 3-calibration / 5-held-out isolation")
    metadata = payload.get("sceneMetadata")
    if not isinstance(metadata, dict):
        raise ValueError("public split is missing sceneMetadata")
    return payload, raw


def scene_source(data_root: Path, entry: dict) -> Path:
    return data_root / "raw" / str(entry["fold"]) / str(entry["videoId"])


def reference_mesh(source: Path, video_id: str) -> Path:
    return source / f"{video_id}_3dod_mesh.ply"


def scene_paths(output_root: Path, scene: str) -> dict[str, Path]:
    root = output_root / "scenes" / scene
    return {
        "root": root,
        "capture": root / "capture",
        "samples": root / "observations.jsonl",
        "sample_meta": root / "observations.jsonl.meta.json",
    }


def concatenate_jsonl(inputs: Iterable[Path], output: Path) -> int:
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


def prepare_scene(
    *,
    repo_root: Path,
    data_root: Path,
    output_root: Path,
    scene: str,
    entry: dict,
    ffmpeg: str,
    proxy_python: str,
    adapter_stride: int,
    maximum_frames: int | None,
    pixel_stride: int,
    frame_stride: int,
    maximum_samples: int,
) -> dict:
    paths = scene_paths(output_root, scene)
    source = scene_source(data_root, entry)
    video_id = str(entry["videoId"])
    mesh = reference_mesh(source, video_id)
    required = (
        source / "confidence",
        source / "lowres_depth",
        source / "lowres_wide",
        source / "lowres_wide_intrinsics",
        source / "lowres_wide.traj",
        mesh,
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise ValueError(f"{scene} is missing acquired assets: {', '.join(missing)}")

    adapter = repo_root / "benchmarks/scripts/adapters/arkitscenes_to_aether.py"
    sampler = repo_root / "benchmarks/scripts/arkit_uncertainty_samples.py"
    if paths["capture"].exists():
        shutil.rmtree(paths["capture"])
    adapter_command = [
        sys.executable,
        str(adapter),
        str(source),
        "--output",
        str(paths["capture"]),
        "--stride",
        str(adapter_stride),
        "--ffmpeg",
        ffmpeg,
    ]
    if maximum_frames is not None:
        adapter_command.extend(["--max-frames", str(maximum_frames)])
    run(adapter_command, cwd=repo_root)

    sample_command = [
        proxy_python,
        str(sampler),
        str(paths["capture"]),
        str(mesh),
        "--scene",
        scene,
        "--output",
        str(paths["samples"]),
        "--pixel-stride",
        str(pixel_stride),
        "--frame-stride",
        str(frame_stride),
        "--max-samples",
        str(maximum_samples),
    ]
    run(sample_command, cwd=repo_root)
    meta = json.loads(paths["sample_meta"].read_text())
    if int(meta.get("emittedSamples", 0)) == 0:
        raise ValueError(f"{scene} emitted no ground-truth uncertainty samples")
    return {
        "scene": scene,
        "role": entry["role"],
        "fold": entry["fold"],
        "videoId": video_id,
        "visitId": entry["visitId"],
        "source": str(source.resolve()),
        "referenceMesh": str(mesh.resolve()),
        "samples": str(paths["samples"].resolve()),
        "sampleSha256": sha256_file(paths["samples"]),
        "emittedSamples": meta["emittedSamples"],
        "referenceMisses": meta["referenceMisses"],
    }


def prepare(
    *,
    repo_root: Path,
    data_root: Path,
    output_root: Path,
    split: dict,
    ffmpeg: str,
    proxy_python: str,
    adapter_stride: int,
    maximum_frames: int | None,
    pixel_stride: int,
    frame_stride: int,
    maximum_samples: int,
) -> list[dict]:
    scenes = split["calibrationScenes"] + split["heldOutScenes"]
    prepared = []
    for scene in scenes:
        prepared.append(
            prepare_scene(
                repo_root=repo_root,
                data_root=data_root,
                output_root=output_root,
                scene=scene,
                entry=split["sceneMetadata"][scene],
                ffmpeg=ffmpeg,
                proxy_python=proxy_python,
                adapter_stride=adapter_stride,
                maximum_frames=maximum_frames,
                pixel_stride=pixel_stride,
                frame_stride=frame_stride,
                maximum_samples=maximum_samples,
            )
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
    inputs = [scene_paths(output_root, scene)["samples"] for scene in split["calibrationScenes"]]
    concatenate_jsonl(inputs, calibration_raw)
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
        raise ValueError("fitter did not produce the expected frozen calibration-only model")
    expected_split_sha = sha256_file(split_path)
    if payload.get("splitSha256") != expected_split_sha:
        raise ValueError("fitted model split hash does not match the frozen study split")
    return fitted


def evaluate(
    *,
    repo_root: Path,
    output_root: Path,
    split: dict,
    fitted_model: Path,
    bootstrap: int,
    bootstrap_seed: int,
) -> dict:
    held_raw = output_root / "held-out/observations.jsonl"
    inputs = [scene_paths(output_root, scene)["samples"] for scene in split["heldOutScenes"]]
    concatenate_jsonl(inputs, held_raw)

    controls = repo_root / "benchmarks/scripts/uncertainty_controls.py"
    predictor = repo_root / "benchmarks/scripts/geometric_uncertainty.py"
    metrics = repo_root / "benchmarks/scripts/uncertainty_metrics.py"

    reports = {}
    for mode, method in (
        ("intact", "u1-intact-confidence"),
        ("constant", "u1-constant-confidence"),
        ("shuffled", "u1-shuffled-confidence"),
    ):
        mode_root = output_root / "held-out" / mode
        controlled = mode_root / "controlled.jsonl"
        annotated = mode_root / "controlled-method.jsonl"
        predictions = mode_root / "predictions.jsonl"
        report = mode_root / "calibration-report.json"
        markdown = mode_root / "calibration-report.md"

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
                str(bootstrap_seed),
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
                str(bootstrap_seed),
            ],
            cwd=repo_root,
        )
        reports[mode] = {
            "method": method,
            "controlledSha256": sha256_file(controlled),
            "predictionsSha256": sha256_file(predictions),
            "report": str(report.resolve()),
            "reportSha256": sha256_file(report),
        }
    return reports


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    default_split = repo_root / "benchmarks/experiments/metric-uncertainty-public-split-v1.json"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("prepare", "fit", "evaluate", "all"), default="all")
    parser.add_argument("--split", type=Path, default=default_split)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    parser.add_argument(
        "--proxy-python",
        default=str(repo_root / ".aether-deps/proxy-venv/bin/python"),
        help="Python with NumPy and Open3D for ground-truth ray sampling",
    )
    parser.add_argument("--adapter-stride", type=int, default=6)
    parser.add_argument("--max-frames", type=int)
    parser.add_argument("--pixel-stride", type=int, default=8)
    parser.add_argument("--frame-stride", type=int, default=1)
    parser.add_argument("--max-samples", type=int, default=500_000)
    parser.add_argument("--max-per-scene", type=int, default=100_000)
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--bootstrap-seed", type=int, default=42)
    args = parser.parse_args()

    try:
        split_path = args.split.resolve()
        split, split_bytes = load_split(split_path)
        output_root = args.output_root.resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        data_root = args.data_root.resolve()

        stage_results: dict = {}
        if args.stage in ("prepare", "all"):
            stage_results["prepare"] = prepare(
                repo_root=repo_root,
                data_root=data_root,
                output_root=output_root,
                split=split,
                ffmpeg=args.ffmpeg,
                proxy_python=args.proxy_python,
                adapter_stride=args.adapter_stride,
                maximum_frames=args.max_frames,
                pixel_stride=args.pixel_stride,
                frame_stride=args.frame_stride,
                maximum_samples=args.max_samples,
            )

        fitted_model = output_root / "calibration/fitted-model.json"
        if args.stage in ("fit", "all"):
            fitted_model = fit(
                repo_root=repo_root,
                output_root=output_root,
                split_path=split_path,
                split=split,
                max_per_scene=args.max_per_scene,
            )
            stage_results["fit"] = {
                "model": str(fitted_model.resolve()),
                "modelSha256": sha256_file(fitted_model),
            }

        if args.stage in ("evaluate", "all"):
            if not fitted_model.is_file():
                raise ValueError("held-out evaluation requires calibration/fitted-model.json")
            model_payload = json.loads(fitted_model.read_text())
            split_sha = hashlib.sha256(split_bytes).hexdigest()
            if model_payload.get("splitSha256") != split_sha:
                raise ValueError("held-out evaluation refuses a fitted model from another split")
            stage_results["evaluate"] = evaluate(
                repo_root=repo_root,
                output_root=output_root,
                split=split,
                fitted_model=fitted_model,
                bootstrap=args.bootstrap,
                bootstrap_seed=args.bootstrap_seed,
            )

        study_ledger = {
            "schemaVersion": 1,
            "study": "metric-uncertainty-v1",
            "stage": args.stage,
            "splitId": split["id"],
            "splitSha256": hashlib.sha256(split_bytes).hexdigest(),
            "dataRoot": str(data_root),
            "outputRoot": str(output_root),
            "results": stage_results,
        }
        ledger_path = output_root / "study-ledger.json"
        ledger_path.write_text(json.dumps(study_ledger, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"ok": True, "ledger": str(ledger_path.resolve())}, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"run_metric_uncertainty_public: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
