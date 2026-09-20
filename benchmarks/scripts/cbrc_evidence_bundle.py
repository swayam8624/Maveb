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
) -> dict:
    if epsilon < 0:
        raise ValueError("epsilon must be non-negative")
    for path in (translation, certificate, oracle):
        if not path.exists():
            raise FileNotFoundError(path)

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
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
