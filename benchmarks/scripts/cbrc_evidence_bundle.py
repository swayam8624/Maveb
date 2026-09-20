#!/usr/bin/env python3
"""Create one reproducible CBRC evidence bundle from a live persistent edit.

This orchestrates, in order:
  translation JSON + post-frame certificate JSON
    -> bound replay manifest
    -> independent full-reference Gaussian oracle
    -> strict actual<=bound<=epsilon evaluation
    -> immutable provenance hashes

No step converts a failed certificate into a successful record.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Iterable


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def run_checked(command: list[str], *, allowed: Iterable[int] = (0,)) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(command, text=True, capture_output=True, check=False)
    if process.returncode not in set(allowed):
        raise RuntimeError(
            f"command failed ({process.returncode}): {' '.join(command)}\n"
            f"stdout:\n{process.stdout[-4000:]}\n"
            f"stderr:\n{process.stderr[-4000:]}"
        )
    return process


def script_path(name: str) -> Path:
    return Path(__file__).resolve().with_name(name)


def validate_native_planner_certificate(
    path: Path, manifest: dict
) -> dict:
    payload = json.loads(path.read_text())
    if payload.get("schemaVersion") != 1:
        raise ValueError("native planner certificate schemaVersion must be 1")
    if payload.get("artifact") != "maveb-cbrc-native-certificate":
        raise ValueError("native planner certificate artifact identity is invalid")
    if payload.get("graphVersion") != manifest.get("graph_scope"):
        raise ValueError("native planner graphVersion disagrees with replay graph_scope")
    if payload.get("boundVersion") != manifest.get("bound_version"):
        raise ValueError("native planner boundVersion disagrees with replay bound_version")

    production = manifest["production_certificate"]["outputConePlanner"]
    comparisons = (
        ("stable", bool(payload.get("stable")), bool(production["stable"])),
        ("passes", bool(payload.get("passes")), bool(production["passes"])),
        (
            "fullRebuild",
            bool(payload.get("fullRebuild")),
            bool(production["fullRepair"]),
        ),
    )
    for name, actual, expected in comparisons:
        if actual != expected:
            raise ValueError(
                f"native planner {name} disagrees with production planner telemetry"
            )

    for native_key, production_key in (
        ("work", "plannerWork"),
        ("fullWork", "fullWork"),
    ):
        native_value = float(payload[native_key])
        production_value = float(production[production_key])
        tolerance = max(
            1e-9,
            1e-9 * max(abs(native_value), abs(production_value), 1.0),
        )
        if abs(native_value - production_value) > tolerance:
            raise ValueError(
                f"native planner {native_key} disagrees with production planner telemetry"
            )

    qois = payload.get("qois")
    if not isinstance(qois, list) or len(qois) != 1:
        raise ValueError("native planner certificate must contain one output QoI")
    qoi = qois[0]
    if qoi.get("name") != "resolved-rgb-linf":
        raise ValueError("native planner QoI name disagrees with production contract")
    for native_key, production_key in (
        ("bound", "resolvedRgbBound"),
        ("epsilon", "epsilon"),
    ):
        native_value = float(qoi[native_key])
        production_value = float(production[production_key])
        tolerance = max(
            1e-9,
            1e-9 * max(abs(native_value), abs(production_value), 1.0),
        )
        if abs(native_value - production_value) > tolerance:
            raise ValueError(
                f"native planner QoI {native_key} disagrees with production telemetry"
            )
    return payload


def bundle(
    *,
    translation: Path,
    certificate: Path,
    oracle: Path,
    scene_id: str,
    git_sha: str,
    epsilon: float,
    output_dir: Path,
    work_cost_model: Path | None = None,
    native_planner_certificate: Path | None = None,
) -> dict:
    if epsilon < 0:
        raise ValueError("epsilon must be non-negative")
    for path in (translation, certificate, oracle):
        if not path.exists():
            raise FileNotFoundError(path)
    if native_planner_certificate is not None and not native_planner_certificate.exists():
        raise FileNotFoundError(native_planner_certificate)

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = output_dir / "replay-manifest.json"
    row = output_dir / "revision-row.json"
    spatial = output_dir / "spatial-evidence.csv"
    rows_jsonl = output_dir / "revision-rows.jsonl"
    evaluation = output_dir / "evaluation.json"

    bind_command = [
        sys.executable,
        str(script_path("cbrc_bind_live_revision.py")),
        "--translation", str(translation),
        "--certificate", str(certificate),
        "--scene-id", scene_id,
        "--git-sha", git_sha,
        "--epsilon", repr(float(epsilon)),
        "--output", str(manifest),
    ]
    if work_cost_model is not None:
        bind_command.extend(["--work-cost-model", str(work_cost_model)])
    run_checked(bind_command)

    manifest_payload = json.loads(manifest.read_text())
    if native_planner_certificate is not None:
        validate_native_planner_certificate(
            native_planner_certificate, manifest_payload
        )
    manifest_payload["spatial_output"] = str(spatial)
    manifest.write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n"
    )

    # Exit 3 from the native oracle means candidate local repair is certified
    # but outside tolerance; cbrc_replay converts it into an explicit FULL row.
    run_checked(
        [
            sys.executable,
            str(script_path("cbrc_replay.py")),
            "--oracle", str(oracle),
            "--manifest", str(manifest),
            "--output", str(row),
        ]
    )

    row_text = row.read_text().strip()
    rows_jsonl.write_text(row_text + "\n")

    run_checked(
        [
            sys.executable,
            str(script_path("cbrc_evaluate.py")),
            "--input", str(rows_jsonl),
            "--output", str(evaluation),
        ]
    )

    eval_payload = json.loads(evaluation.read_text())
    if not bool(eval_payload.get("pass", False)):
        raise RuntimeError("strict CBRC evidence evaluation did not pass")

    artifacts = {
        "translation": translation,
        "certificate": certificate,
        "manifest": manifest,
        "row": row,
        "rows": rows_jsonl,
        "evaluation": evaluation,
        "spatial": spatial,
    }
    if work_cost_model is not None:
        artifacts["workCostModel"] = work_cost_model
    if native_planner_certificate is not None:
        artifacts["nativePlannerCertificate"] = native_planner_certificate

    provenance = {
        "schemaVersion": 1,
        "experiment": "cbrc-live-evidence-bundle-v1",
        "sceneId": scene_id,
        "gitSha": git_sha,
        "epsilon": epsilon,
        "oracle": str(oracle),
        "oracleSha256": sha256(oracle),
        "artifacts": {
            name: {"path": str(path), "sha256": sha256(path)}
            for name, path in artifacts.items()
        },
        "evaluationPass": True,
    }
    provenance_path = output_dir / "provenance.json"
    provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    return provenance


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--translation", type=Path, required=True)
    parser.add_argument("--certificate", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--scene-id", required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--epsilon", type=float, required=True)
    parser.add_argument("--work-cost-model", type=Path)
    parser.add_argument("--native-planner-certificate", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = bundle(
        translation=args.translation,
        certificate=args.certificate,
        oracle=args.oracle,
        scene_id=args.scene_id,
        git_sha=args.git_sha,
        epsilon=args.epsilon,
        output_dir=args.output_dir,
        work_cost_model=args.work_cost_model,
        native_planner_certificate=args.native_planner_certificate,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
