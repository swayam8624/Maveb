#!/usr/bin/env python3
"""Freeze scientific artifacts exposed before the U3b runtime failure."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


SCENES = (
    "ca1m-48458481",
    "ca1m-48018737",
    "ca1m-45261587",
    "ca1m-42897538",
    "ca1m-48018375",
)
METHODS = (
    "uniform",
    "naive-confidence",
    "u3v1-absolute-inverse-variance",
    "relative-confidence-precision",
    "relative-confidence-shuffled",
)
EXPECTED_COMPLETED = tuple(
    [(scene, method) for scene in SCENES[:3] for method in METHODS]
    + [(SCENES[3], "uniform")]
)
FAILURE_KEY = (SCENES[3], "naive-confidence")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def f_score_at(metrics: dict, threshold: float = 0.05) -> float:
    for record in metrics["fScores"]:
        if abs(float(record["threshold"]) - threshold) <= 1e-12:
            return float(record["fScore"])
    raise ValueError(f"geometry report has no F-score at {threshold}")


def complete_artifact(method_dir: Path) -> bool:
    return all((method_dir / name).is_file() for name in ("mesh.ply", "fusion.json", "geometry.json"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--fuse-tool", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if (args.output_root / "primary-result.json").exists():
        raise ValueError("primary-result.json already exists; this is not a pre-result failure snapshot")
    if not args.fuse_tool.is_file():
        raise FileNotFoundError(args.fuse_tool)
    if args.output.exists():
        raise ValueError("partial reveal snapshot already exists and will not be overwritten")

    completed: list[dict] = []
    incomplete: list[dict] = []
    observed_complete_keys: list[tuple[str, str]] = []

    for scene in SCENES:
        for method in METHODS:
            method_dir = args.output_root / "scenes" / scene / "primary" / method
            mesh = method_dir / "mesh.ply"
            fusion_path = method_dir / "fusion.json"
            geometry_path = method_dir / "geometry.json"
            key = (scene, method)

            if complete_artifact(method_dir):
                observed_complete_keys.append(key)
                geometry = json.loads(geometry_path.read_text())
                fusion = json.loads(fusion_path.read_text())
                metrics = geometry["metrics"]
                completed.append(
                    {
                        "scene": scene,
                        "method": method,
                        "meshSha256": sha256_file(mesh),
                        "geometrySha256": sha256_file(geometry_path),
                        "fusionSha256": sha256_file(fusion_path),
                        "chamferMeanMetres": float(metrics["chamferMean"]),
                        "fScoreAt5cm": f_score_at(metrics),
                        "vertices": int(fusion["vertices"]),
                        "triangles": int(fusion["triangles"]),
                    }
                )
            else:
                incomplete.append(
                    {
                        "scene": scene,
                        "method": method,
                        "directoryExists": method_dir.exists(),
                        "meshExists": mesh.is_file(),
                        "fusionExists": fusion_path.is_file(),
                        "geometryExists": geometry_path.is_file(),
                    }
                )

    if tuple(observed_complete_keys) != EXPECTED_COMPLETED:
        raise ValueError(
            "partial reveal boundary differs from the frozen runtime-recovery protocol: "
            f"observed={observed_complete_keys!r} expected={EXPECTED_COMPLETED!r}"
        )

    failure_records = [
        record
        for record in incomplete
        if (record["scene"], record["method"]) == FAILURE_KEY
    ]
    if len(failure_records) != 1:
        raise ValueError("failed naive-confidence method is missing from incomplete inventory")
    if failure_records[0]["meshExists"] or failure_records[0]["fusionExists"] or failure_records[0]["geometryExists"]:
        raise ValueError("failed naive-confidence method unexpectedly contains completed artifacts")

    payload = {
        "schemaVersion": 1,
        "study": "metric-uncertainty-u3b-relative-confidence-transfer-v1",
        "stage": "U3b-runtime-failure-pre-fix-snapshot",
        "status": "frozen-pre-fix-partial-reveal",
        "runtimeRecoveryProtocol": "benchmarks/experiments/metric-uncertainty-u3b-runtime-recovery-v1.json",
        "fuseTool": str(args.fuse_tool),
        "fuseToolSha256": sha256_file(args.fuse_tool),
        "completedMethodCount": len(completed),
        "failure": {
            "scene": FAILURE_KEY[0],
            "method": FAILURE_KEY[1],
            "completedArtifactsPresent": False,
        },
        "completed": completed,
        "incomplete": incomplete,
        "replayRequirement": "Every completed meshSha256 must match exactly after the runtime fix.",
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(args.output)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
