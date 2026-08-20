#!/usr/bin/env python3
"""Re-evaluate a completed U3 pose preflight against the frozen manifest pass rule.

The original preflight implementation accidentally added a minimum comparable-pair
count that was never preregistered. This correction does not recompute any geometry
or cross-projection measurements. It consumes the completed preflight JSON, applies
only the frozen manifest rule, preserves the input SHA-256, and emits a corrected
gate artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scene_passes_frozen_rule(validation: dict) -> bool:
    pair_count = int(validation["pairCount"])
    direct_wins = int(validation["cameraToWorldBetterPairCount"])
    direct_median = float(validation["cameraToWorldMedianOfPairMedianErrorsMetres"])
    inverse_median = float(validation["inverseMedianOfPairMedianErrorsMetres"])
    return (
        pair_count > 0
        and direct_wins > pair_count / 2
        and direct_median < inverse_median
    )


def apply_gate(payload: dict, input_sha256: str) -> dict:
    scenes = []
    for scene in payload["scenes"]:
        validation = scene["poseConventionValidation"]
        frozen_pass = scene_passes_frozen_rule(validation)
        scenes.append(
            {
                "videoId": scene["videoId"],
                "pairCount": validation["pairCount"],
                "cameraToWorldBetterPairCount": validation[
                    "cameraToWorldBetterPairCount"
                ],
                "cameraToWorldMedianOfPairMedianErrorsMetres": validation[
                    "cameraToWorldMedianOfPairMedianErrorsMetres"
                ],
                "inverseMedianOfPairMedianErrorsMetres": validation[
                    "inverseMedianOfPairMedianErrorsMetres"
                ],
                "legacyImplementationPassed": validation.get("passed"),
                "frozenManifestRulePassed": frozen_pass,
            }
        )

    passed = bool(scenes) and all(scene["frozenManifestRulePassed"] for scene in scenes)
    return {
        "schemaVersion": 1,
        "study": "metric-uncertainty-v1",
        "stage": "U3-ca1m-pose-preflight-manifest-gate-correction",
        "status": "passed" if passed else "failed",
        "inputPreflightSha256": input_sha256,
        "inputPreflightReportedStatus": payload.get("status"),
        "frozenPassRule": (
            "released interpretation must have lower scene median cross-projection "
            "depth disagreement and win a majority of comparable adjacent-frame pairs "
            "in every evaluation scene"
        ),
        "implementationCorrection": (
            "removed accidental minimum-comparable-pair threshold; no measurements, "
            "scene IDs, frame selections, or reconstruction outputs were changed"
        ),
        "scenes": scenes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    raw = args.input.read_bytes()
    payload = json.loads(raw)
    if payload.get("stage") != "U3-ca1m-pose-preflight":
        raise ValueError("input is not a U3 CA-1M pose preflight artifact")

    result = apply_gate(payload, hashlib.sha256(raw).hexdigest())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
