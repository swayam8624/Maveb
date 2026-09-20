#!/usr/bin/env python3
"""Run one manifest-bound CBRC Gaussian full-reference replay.

Exit semantics of the C++ oracle:
  0: certificate holds and candidate bound <= epsilon
  3: certificate holds but candidate bound > epsilon
  4: certificate violation (fatal)
  other: execution/configuration failure

When code 3 is returned, this runner records the principled CBRC decision:
fallback to FULL. The rejected local candidate remains in candidateDiagnostics.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def require_number(data: dict[str, Any], key: str, *, positive: bool = False) -> float:
    value = float(data[key])
    if positive and value <= 0:
        raise ValueError(f"{key} must be positive")
    if not positive and value < 0:
        raise ValueError(f"{key} must be non-negative")
    return value


def build_oracle_command(binary: Path, manifest: dict[str, Any]) -> list[str]:
    camera = manifest["camera"]
    background = camera.get("background", [0.0, 0.0, 0.0])
    camera_world_position = camera.get("camera_world_position", [0.0, 0.0, 0.0])
    world_to_camera = camera.get(
        "world_to_camera",
        [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ],
    )
    if len(camera_world_position) != 3:
        raise ValueError("camera_world_position must contain 3 values")
    if len(world_to_camera) != 16:
        raise ValueError("world_to_camera must contain 16 row-major values")
    changed = manifest["changed_indices"]
    if not isinstance(changed, list) or not changed:
        raise ValueError("changed_indices must be a non-empty list")

    command = [
        str(binary),
        "--before", str(manifest["before_ply"]),
        "--after", str(manifest["after_ply"]),
        "--changed", ",".join(str(int(i)) for i in changed),
        "--width", str(int(camera["width"])),
        "--height", str(int(camera["height"])),
        "--focal-x", str(float(camera["focal_x"])),
        "--focal-y", str(float(camera["focal_y"])),
        "--center-x", str(float(camera["center_x"])),
        "--center-y", str(float(camera["center_y"])),
        "--near", str(float(camera.get("near", 0.01))),
        "--far", str(float(camera.get("far", 10000.0))),
        "--world-to-camera", ",".join(str(float(v)) for v in world_to_camera),
        "--camera-world-position", ",".join(
            str(float(v)) for v in camera_world_position
        ),
        "--epsilon", str(float(manifest["epsilon_rgb_linf"])),
        "--background-r", str(float(background[0])),
        "--background-g", str(float(background[1])),
        "--background-b", str(float(background[2])),
    ]
    return command


def finalize_row(
    manifest: dict[str, Any],
    oracle: dict[str, Any],
    returncode: int,
) -> dict[str, Any]:
    if returncode == 4 or oracle.get("certified") is False:
        raise RuntimeError(
            "FATAL CBRC certificate violation: actual full-reference error exceeded bound"
        )
    if returncode not in (0, 3):
        raise RuntimeError(f"oracle failed with exit code {returncode}")

    full_work = require_number(manifest, "full_work", positive=True)
    candidate_work = require_number(manifest, "candidate_work")
    total_nodes = int(manifest["total_nodes"])
    hard_nodes = int(manifest["hard_closure_nodes"])
    candidate_nodes = int(manifest["candidate_cone_nodes"])
    if total_nodes <= 0 or not (0 <= hard_nodes <= candidate_nodes <= total_nodes):
        raise ValueError("invalid hard/candidate/total node cardinalities")

    candidate_qoi = oracle["qois"]["rgb_linf"]
    fallback = returncode == 3 or not bool(oracle.get("withinTolerance", False))

    if fallback:
        # The selected execution becomes the full rebuild. Its stale-error
        # certificate relative to itself is exactly zero. Preserve the rejected
        # local candidate below for crossover analysis.
        qoi = {
            "epsilon": float(candidate_qoi["epsilon"]),
            "certified_bound": 0.0,
            "measured_full_reference_error": 0.0,
        }
        cone_nodes = total_nodes
        planner_work = full_work
    else:
        qoi = {
            "epsilon": float(candidate_qoi["epsilon"]),
            "certified_bound": float(candidate_qoi["certified_bound"]),
            "measured_full_reference_error": float(
                candidate_qoi["measured_full_reference_error"]
            ),
        }
        cone_nodes = candidate_nodes
        planner_work = candidate_work

    return {
        "schemaVersion": 1,
        "scene_id": str(manifest["scene_id"]),
        "revision_id": str(manifest["revision_id"]),
        "git_sha": str(manifest["git_sha"]),
        "method": "CBRC",
        "edit_class": str(manifest.get("edit_class", "gaussian")),
        "coupling_regime": str(manifest.get("coupling_regime", "unknown")),
        "changed_fraction": float(oracle["changedFraction"]),
        "graph_version": str(manifest["graph_version"]),
        "bound_version": str(manifest["bound_version"]),
        "hard_closure_nodes": hard_nodes,
        "repair_cone_nodes": cone_nodes,
        "total_nodes": total_nodes,
        "fallback_full": fallback,
        "stable": True,
        "planner_work": planner_work,
        "full_work": full_work,
        "qois": {"rgb_linf": qoi},
        "work_ledger": manifest.get("work_ledger", {}),
        "candidateDiagnostics": {
            "candidateConeNodes": candidate_nodes,
            "candidateWork": candidate_work,
            "candidateRgbBound": float(candidate_qoi["certified_bound"]),
            "candidateActualRgbError": float(
                candidate_qoi["measured_full_reference_error"]
            ),
            "candidateWithinTolerance": bool(oracle.get("withinTolerance", False)),
            "affectedPixelFraction": float(oracle["affectedPixelFraction"]),
            "effectivity": float(oracle["effectivity"]),
            "certificateViolationPixels": int(
                oracle["certificateViolationPixels"]
            ),
        },
    }


def run_manifest(binary: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    process = subprocess.run(
        build_oracle_command(binary, manifest),
        capture_output=True,
        text=True,
        check=False,
    )
    if not process.stdout.strip():
        raise RuntimeError(
            f"oracle emitted no JSON (code {process.returncode}): {process.stderr.strip()}"
        )
    try:
        oracle = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"oracle output is not JSON: {process.stdout[:500]}"
        ) from error

    if process.returncode not in (0, 3, 4):
        raise RuntimeError(
            f"oracle execution failed ({process.returncode}): {process.stderr.strip()}"
        )
    return finalize_row(manifest, oracle, process.returncode)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text())
    row = run_manifest(args.oracle, manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
    temporary.replace(args.output)
    print(json.dumps(row, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
