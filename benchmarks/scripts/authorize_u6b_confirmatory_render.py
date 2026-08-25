#!/usr/bin/env python3
"""Freeze U6b render authorization after preparation and before any confirmatory render."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from run_u5a_gaussian_depth import sha256_file


STUDY_ID = "metric-uncertainty-u6b-opacity-visibility-confirmatory-v1"
PROTOCOL_SHA256 = "0c58590d7c71c24797d583bd2681c1fc8994028d9b188b1fbe5fb5a4c4e1b3e3"
RENDER_TOOL_SHA256 = "6b1f511633c259890b0f531ac414773a6a2bcbfcf5ee932585db036cfd4a997d"
EXPECTED_SCENES = [
    "ca1m-42898811",
    "ca1m-45261121",
    "ca1m-47895341",
    "ca1m-47332915",
    "ca1m-47331971",
]
METHODS = [
    "depth-only-fixed-opacity",
    "calibrated-relative-precision-opacity",
    "shuffled-relative-precision-opacity",
]


def validate_preparation(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    prep = json.loads(path.read_text())
    if prep.get("study") != STUDY_ID:
        raise ValueError("U6b authorization preparation study mismatch")
    if prep.get("status") != "prepared-no-u6b-render-or-metric-outcomes":
        raise ValueError("U6b authorization requires prepared-no-outcome status")
    if prep.get("protocolSha256") != PROTOCOL_SHA256:
        raise ValueError("U6b authorization preparation protocol SHA mismatch")
    if prep.get("noRenderedDepthProduced") is not True or prep.get("noU6bMetricsProduced") is not True:
        raise ValueError("U6b preparation crossed the outcome boundary")
    if prep.get("methods") != METHODS:
        raise ValueError("U6b preparation method order changed")
    scenes = prep.get("scenes", [])
    if [scene["scene"] for scene in scenes] != EXPECTED_SCENES:
        raise ValueError("U6b preparation scene order changed")
    return prep


def inspect_assets(prep: dict) -> tuple[list[dict], int, int, int]:
    scene_records: list[dict] = []
    ply_count = 0
    target_manifest_count = 0
    faro_target_count = 0

    for scene in prep["scenes"]:
        method_records: dict[str, dict] = {}
        primitive_counts: set[int] = set()
        for method in METHODS:
            record = scene["methods"][method]
            path = Path(record["gaussianPath"])
            if not path.is_file() or sha256_file(path) != record["gaussianSha256"]:
                raise ValueError(f"U6b authorization Gaussian SHA mismatch: {scene['scene']} {method}")
            primitive_counts.add(int(record["primitiveCount"]))
            method_records[method] = {
                "gaussianSha256": record["gaussianSha256"],
                "primitiveCount": int(record["primitiveCount"]),
            }
            ply_count += 1
        if len(primitive_counts) != 1 or next(iter(primitive_counts)) != int(scene["primitiveCount"]):
            raise ValueError(f"U6b authorization primitive counts differ for {scene['scene']}")

        target_manifest = Path(scene["targetManifestPath"])
        if not target_manifest.is_file() or sha256_file(target_manifest) != scene["targetManifestSha256"]:
            raise ValueError(f"U6b authorization target manifest SHA mismatch: {scene['scene']}")
        target_payload = json.loads(target_manifest.read_text())
        targets = target_payload.get("targets", [])
        if len(targets) != 8:
            raise ValueError(f"U6b authorization target count differs from eight: {scene['scene']}")
        indices = [int(target["targetIndex"]) for target in targets]
        if indices != list(range(8)):
            raise ValueError(f"U6b authorization target order changed: {scene['scene']}")
        target_hashes: list[dict] = []
        for target in targets:
            faro = Path(target["faroDepthPath"])
            if not faro.is_file() or sha256_file(faro) != target["faroDepthSha256"]:
                raise ValueError(f"U6b authorization FARO target SHA mismatch: {scene['scene']}")
            target_hashes.append(
                {
                    "targetIndex": int(target["targetIndex"]),
                    "timestampNanoseconds": int(target["timestampNanoseconds"]),
                    "faroDepthSha256": target["faroDepthSha256"],
                }
            )
            faro_target_count += 1
        target_manifest_count += 1
        scene_records.append(
            {
                "scene": scene["scene"],
                "visitId": str(scene["visitId"]),
                "primitiveCount": int(scene["primitiveCount"]),
                "methods": method_records,
                "targetManifestSha256": scene["targetManifestSha256"],
                "targets": target_hashes,
            }
        )

    return scene_records, ply_count, target_manifest_count, faro_target_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--preparation", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--render-tool", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    args = parser.parse_args()

    if not args.protocol.is_file() or sha256_file(args.protocol) != PROTOCOL_SHA256:
        raise ValueError("U6b authorization protocol SHA mismatch")
    prep = validate_preparation(args.preparation)
    if not args.render_tool.is_file() or sha256_file(args.render_tool) != RENDER_TOOL_SHA256:
        raise ValueError("U6b authorization renderer SHA mismatch")
    if args.authorization.exists():
        raise ValueError("U6b render authorization already exists; authorization will not be overwritten")
    if (args.output_root / "result.json").exists():
        raise ValueError("U6b confirmatory result already exists before authorization")
    existing_renders = list(args.output_root.glob("scenes/*/renders/*/*.f32"))
    if existing_renders:
        raise ValueError("U6b renders already exist before authorization")

    scene_records, ply_count, target_manifest_count, faro_target_count = inspect_assets(prep)
    if ply_count != 15:
        raise ValueError(f"U6b authorization expected 15 PLYs, found {ply_count}")
    if target_manifest_count != 5:
        raise ValueError(f"U6b authorization expected 5 target manifests, found {target_manifest_count}")
    if faro_target_count != 40:
        raise ValueError(f"U6b authorization expected 40 FARO targets, found {faro_target_count}")

    payload = {
        "schemaVersion": 1,
        "study": STUDY_ID,
        "stage": "U6b-confirmatory-render-authorization",
        "status": "authorized-after-frozen-preparation-before-render",
        "protocolSha256": PROTOCOL_SHA256,
        "preparationSha256": sha256_file(args.preparation),
        "renderToolSha256": RENDER_TOOL_SHA256,
        "methods": METHODS,
        "sceneCount": 5,
        "targetViewsPerScene": 8,
        "totalRenderCount": 120,
        "gaussianPlyCount": ply_count,
        "targetManifestCount": target_manifest_count,
        "faroTargetDepthCount": faro_target_count,
        "existingRenderedDepthCount": 0,
        "confirmatoryOutcomeObservedBeforeAuthorization": False,
        "scenes": scene_records,
        "claimBoundary": "This artifact authorizes only the single frozen U6b confirmatory render reveal after preparation has been hashed and verified. It contains no rendered depth, FARO metric, bootstrap statistic, gate decision, or confirmatory outcome.",
    }
    args.authorization.parent.mkdir(parents=True, exist_ok=True)
    args.authorization.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
