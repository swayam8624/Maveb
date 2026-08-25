#!/usr/bin/env python3
"""Render and evaluate frozen U6a opacity-only Gaussian visibility variants."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from run_u5a_gaussian_depth import (
    paired_bootstrap_median,
    run_json,
    scene_summary,
    sha256_file,
    target_metrics,
)


STUDY_ID = "metric-uncertainty-u6a-opacity-visibility-v1"
U5A_RESULT_SHA256 = "5f0d70442ec1973eb28f1b61e7fe8cb174afdabfcae3aa64ab478c479ab32362"
RENDER_TOOL_SHA256 = "6b1f511633c259890b0f531ac414773a6a2bcbfcf5ee932585db036cfd4a997d"
EXPECTED_SCENES = [
    "ca1m-48458481",
    "ca1m-48018737",
    "ca1m-45261587",
    "ca1m-42897538",
    "ca1m-48018375",
]
BASELINE_U5A_METHOD = "depth-only-covariance"
BASELINE_METHOD = "depth-only-fixed-opacity"
NEW_METHODS = (
    "calibrated-relative-precision-opacity",
    "shuffled-relative-precision-opacity",
)


def validate_inputs(args: argparse.Namespace) -> tuple[dict, dict, dict]:
    for path in (args.protocol, args.preparation, args.u5a_result):
        if not path.is_file():
            raise FileNotFoundError(path)
    if not args.render_tool.is_file():
        raise FileNotFoundError(args.render_tool)

    protocol = json.loads(args.protocol.read_text())
    if (
        protocol.get("id") != STUDY_ID
        or protocol.get("status") != "frozen-before-u6a-assets-or-outcomes"
        or not protocol.get("frozen")
    ):
        raise ValueError("U6a protocol is not frozen")
    if protocol.get("scenes") != EXPECTED_SCENES:
        raise ValueError("U6a scene order differs from protocol")
    if protocol["renderPlan"]["newRenderCount"] != 80:
        raise ValueError("U6a frozen render count changed")

    preparation = json.loads(args.preparation.read_text())
    if (
        preparation.get("study") != STUDY_ID
        or preparation.get("status") != "prepared-no-u6a-render-or-metric-outcomes"
        or not preparation.get("noRenderedDepthProduced")
        or not preparation.get("noU6aMetricsProduced")
    ):
        raise ValueError("U6a preparation is not admissible")
    if preparation.get("protocolSha256") != sha256_file(args.protocol):
        raise ValueError("U6a preparation protocol SHA mismatch")
    if preparation.get("u5aResultSha256") != U5A_RESULT_SHA256:
        raise ValueError("U6a preparation U5a result SHA mismatch")

    if sha256_file(args.u5a_result) != U5A_RESULT_SHA256:
        raise ValueError("U6a requires the exact frozen U5a result")
    u5a_result = json.loads(args.u5a_result.read_text())
    if u5a_result.get("status") != "completed-exploratory-gaussian-depth-study":
        raise ValueError("U6a U5a result status is unexpected")
    if sha256_file(args.render_tool) != RENDER_TOOL_SHA256:
        raise ValueError("U6a renderer binary SHA differs from the frozen U5a renderer")
    return protocol, preparation, u5a_result


def verify_and_copy_baseline(
    *, scene: str, u5a_root: Path, u5a_scene: dict, target_manifest: dict
) -> dict:
    method = u5a_scene["methods"][BASELINE_U5A_METHOD]
    targets_by_index = {int(record["targetIndex"]): record for record in method["targets"]}
    if set(targets_by_index) != set(range(8)):
        raise ValueError(f"U6a U5a baseline target indices differ for {scene}")
    copied_targets: list[dict] = []
    for target in target_manifest["targets"]:
        index = int(target["targetIndex"])
        prior = targets_by_index[index]
        render_path = (
            u5a_root
            / "scenes"
            / scene
            / "renders"
            / BASELINE_U5A_METHOD
            / f"{index:02d}.f32"
        )
        if not render_path.is_file() or sha256_file(render_path) != prior["renderSha256"]:
            raise ValueError(f"U6a U5a baseline render SHA mismatch for {scene} target {index}")
        copied_targets.append(dict(prior))
    recomputed = scene_summary(copied_targets)
    if recomputed != method["sceneSummary"]:
        raise ValueError(f"U6a U5a baseline scene summary changed for {scene}")
    return {
        "reusedFromU5a": True,
        "u5aMethod": BASELINE_U5A_METHOD,
        "gaussianSha256": method["gaussianSha256"],
        "primitiveCount": int(method["primitiveCount"]),
        "targets": copied_targets,
        "sceneSummary": recomputed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--preparation", type=Path, required=True)
    parser.add_argument("--u5a-result", type=Path, required=True)
    parser.add_argument("--u5a-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--render-tool", type=Path, required=True)
    args = parser.parse_args()

    protocol, preparation, u5a_result = validate_inputs(args)
    result_path = args.output_root / "result.json"
    if result_path.exists():
        raise ValueError("U6a result.json already exists; exploratory outcome will not be overwritten")

    prep_by_scene = {record["scene"]: record for record in preparation["scenes"]}
    scene_results: dict[str, dict] = {}
    new_render_count = 0

    for scene in EXPECTED_SCENES:
        prep_scene = prep_by_scene.get(scene)
        if prep_scene is None:
            raise ValueError(f"U6a preparation is missing {scene}")
        target_manifest_path = Path(prep_scene["targetManifestPath"])
        if (
            not target_manifest_path.is_file()
            or sha256_file(target_manifest_path) != prep_scene["targetManifestSha256"]
        ):
            raise ValueError(f"U6a target manifest SHA mismatch for {scene}")
        target_manifest = json.loads(target_manifest_path.read_text())
        targets = target_manifest["targets"]
        if len(targets) != 8:
            raise ValueError(f"U6a {scene} target count differs from eight")

        u5a_scene = u5a_result["scenes"][scene]
        method_results: dict[str, dict] = {
            BASELINE_METHOD: verify_and_copy_baseline(
                scene=scene,
                u5a_root=args.u5a_root,
                u5a_scene=u5a_scene,
                target_manifest=target_manifest,
            )
        }

        for method in NEW_METHODS:
            method_prep = prep_scene["methods"][method]
            gaussian_path = Path(method_prep["gaussianPath"])
            if (
                not gaussian_path.is_file()
                or sha256_file(gaussian_path) != method_prep["gaussianSha256"]
            ):
                raise ValueError(f"U6a Gaussian SHA mismatch for {scene} {method}")
            if not method_prep.get("onlyOpacityChangedFromBaseline"):
                raise ValueError(f"U6a preparation did not certify opacity-only change for {scene} {method}")

            target_results: list[dict] = []
            for target in targets:
                target_index = int(target["targetIndex"])
                render_dir = args.output_root / "scenes" / scene / "renders" / method
                render_dir.mkdir(parents=True, exist_ok=True)
                rendered_path = render_dir / f"{target_index:02d}.f32"
                if rendered_path.exists():
                    raise ValueError(
                        f"U6a render already exists before first complete result: {rendered_path}"
                    )
                render_json = run_json(
                    [
                        str(args.render_tool),
                        str(gaussian_path),
                        str(target_manifest_path),
                        "--target-index",
                        str(target_index),
                        "--output",
                        str(rendered_path),
                        "--json",
                    ],
                    label=f"render {scene} {method} target {target_index}",
                )
                new_render_count += 1

                width = int(target["width"])
                height = int(target["height"])
                rendered = np.fromfile(rendered_path, dtype="<f4")
                faro_path = Path(target["faroDepthPath"])
                if (
                    not faro_path.is_file()
                    or sha256_file(faro_path) != target["faroDepthSha256"]
                ):
                    raise ValueError(f"U6a FARO SHA mismatch for {scene} target {target_index}")
                faro = np.fromfile(faro_path, dtype="<f4")
                expected = width * height
                if rendered.size != expected or faro.size != expected:
                    raise ValueError(f"U6a target byte count mismatch for {scene} target {target_index}")
                metrics = target_metrics(
                    rendered.reshape(height, width),
                    faro.reshape(height, width),
                )
                record = {
                    "targetIndex": target_index,
                    "timestampNanoseconds": int(target["timestampNanoseconds"]),
                    "renderSha256": sha256_file(rendered_path),
                    "render": render_json,
                    **metrics,
                }
                target_results.append(record)
                print(
                    json.dumps(
                        {
                            "u6aMetric": {
                                "scene": scene,
                                "method": method,
                                "target": target_index,
                                "within5cm": metrics["within5cmFractionOfFaroValid"],
                                "coverage": metrics["coverageFraction"],
                                "maeMetres": metrics["absoluteDepthErrorMeanMetres"],
                            }
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
            method_results[method] = {
                "reusedFromU5a": False,
                "gaussianSha256": method_prep["gaussianSha256"],
                "primitiveCount": int(method_prep["primitiveCount"]),
                "targets": target_results,
                "sceneSummary": scene_summary(target_results),
            }

        scene_results[scene] = {
            "targetManifestSha256": prep_scene["targetManifestSha256"],
            "methods": method_results,
        }

    if new_render_count != int(protocol["renderPlan"]["newRenderCount"]):
        raise ValueError("U6a did not produce exactly the frozen 80 new renders")

    candidate_vs_baseline: list[float] = []
    candidate_vs_shuffled: list[float] = []
    candidate_better_baseline = 0
    candidate_better_shuffled = 0
    for scene in EXPECTED_SCENES:
        methods = scene_results[scene]["methods"]
        baseline = methods[BASELINE_METHOD]["sceneSummary"]["primaryWithin5cmFractionOfFaroValid"]
        candidate = methods["calibrated-relative-precision-opacity"]["sceneSummary"][
            "primaryWithin5cmFractionOfFaroValid"
        ]
        shuffled = methods["shuffled-relative-precision-opacity"]["sceneSummary"][
            "primaryWithin5cmFractionOfFaroValid"
        ]
        delta_baseline = float(candidate - baseline)
        delta_shuffled = float(candidate - shuffled)
        candidate_vs_baseline.append(delta_baseline)
        candidate_vs_shuffled.append(delta_shuffled)
        candidate_better_baseline += int(delta_baseline > 0.0)
        candidate_better_shuffled += int(delta_shuffled > 0.0)

    comparison = {
        "candidateMinusBaseline": paired_bootstrap_median(
            candidate_vs_baseline,
            replicates=int(protocol["evaluation"]["bootstrapReplicates"]),
            seed=int(protocol["evaluation"]["bootstrapSeed"]),
        ),
        "candidateMinusShuffled": paired_bootstrap_median(
            candidate_vs_shuffled,
            replicates=int(protocol["evaluation"]["bootstrapReplicates"]),
            seed=int(protocol["evaluation"]["bootstrapSeed"]),
        ),
        "candidateBetterThanBaselineSceneCount": candidate_better_baseline,
        "candidateBetterThanShuffledSceneCount": candidate_better_shuffled,
        "descriptiveOnly": True,
    }

    payload = {
        "schemaVersion": 1,
        "study": STUDY_ID,
        "stage": "U6a-exploratory-heldout-depth",
        "status": "completed-exploratory-opacity-visibility-study",
        "claimType": protocol["claimType"],
        "protocolSha256": sha256_file(args.protocol),
        "preparationSha256": sha256_file(args.preparation),
        "u5aResultSha256": sha256_file(args.u5a_result),
        "renderToolSha256": sha256_file(args.render_tool),
        "newRenderCount": new_render_count,
        "reusedBaselineRenderCount": 40,
        "scenes": scene_results,
        "descriptiveComparison": comparison,
        "claimBoundary": "Exploratory only on already-exposed U5a rooms and targets. A positive visibility mechanism requires a separately frozen untouched U6b study before any efficacy claim.",
    }
    result_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
