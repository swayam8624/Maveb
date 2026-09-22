#!/usr/bin/env python3
"""Bind one live persistent Gaussian edit to a reproducible CBRC oracle manifest.

Inputs come from:
  1. Persistent Gaussian edit transaction JSON (transaction/revision provenance)
  2. AetherPersistentRevisionCertificateJSON (post-frame camera/certificate/work)

This is the v1 hybrid production path: the physical Gaussian source set is
supplied exactly by the persistent transaction, while the Gaussian->image->
temporal output repair cone is selected by the native CBRC planner. It does not
claim that CBRC chooses which physical source Gaussians were edited.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


GAUSSIAN_OUTPUT_GRAPH_VERSION = "gaussian-output-cone-v2"
GAUSSIAN_TEMPORAL_BOUND_VERSION = "gaussian-image-temporal-v1"
HEADLESS_TEMPORAL_PIXEL_COST_MODEL_VERSION = "temporal-pixel-work-v1"


def load_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def bind(
    translation: dict[str, Any],
    certificate: dict[str, Any],
    *,
    scene_id: str,
    git_sha: str,
    epsilon: float,
    work_cost_model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not bool(translation.get("persisted", False)):
        raise ValueError("persistent edit revision was not durably persisted")
    if not bool(certificate.get("available", False)):
        raise ValueError("post-frame Gaussian certificate is unavailable")

    before_state = str(translation.get("beforeGaussianSidecar", "")).strip()
    after_state = str(translation.get("afterGaussianSidecar", "")).strip()
    input_format = str(translation.get("gaussianInputFormat", "")).strip()
    if not before_state or not after_state:
        raise ValueError("edit response is missing immutable Gaussian sidecars")
    if input_format != "aether-bin":
        raise ValueError("live binder currently requires canonical aether-bin sidecars")

    total_gaussians = int(translation.get("gaussianCount", 0))
    edit_kind = str(translation.get("editKind", "translation"))
    edited = int(
        translation.get(
            "editedGaussians",
            translation.get("translatedGaussians", 0),
        )
    )
    inspected = int(translation.get("gaussiansInspected", 0))
    used_overlay = bool(translation.get("usedOverlayIndex", False))
    overlay_valid = bool(translation.get("overlayIndexValid", True))
    certified_changed = int(certificate.get("changedGaussians", 0))
    if total_gaussians <= 0:
        raise ValueError("gaussianCount must be positive")
    if edit_kind not in {"translation", "rotation", "uniform-scale", "opacity"}:
        raise ValueError(f"unsupported headless edit kind: {edit_kind}")
    if not 0 < edited <= total_gaussians:
        raise ValueError("editedGaussians is outside the scene cardinality")
    if certified_changed != edited:
        raise ValueError(
            "post-frame certificate changed-Gaussian count disagrees with transaction"
        )
    if not 0 <= inspected <= total_gaussians:
        raise ValueError("gaussiansInspected is outside the scene cardinality")

    camera = certificate.get("camera")
    if not isinstance(camera, dict):
        raise ValueError("post-frame certificate is missing exact camera")
    world_to_camera = camera.get("worldToCamera")
    camera_position = camera.get("cameraWorldPosition")
    if not isinstance(world_to_camera, list) or len(world_to_camera) != 16:
        raise ValueError("camera.worldToCamera must contain 16 values")
    if not isinstance(camera_position, list) or len(camera_position) != 3:
        raise ValueError("camera.cameraWorldPosition must contain 3 values")

    publication = certificate.get("publication")
    temporal = certificate.get("temporal")
    if not isinstance(publication, dict) or not isinstance(temporal, dict):
        raise ValueError("certificate publication/temporal telemetry is required")

    output_plan = certificate.get("outputConePlanner")
    if not isinstance(output_plan, dict) or not bool(output_plan.get("available", False)):
        raise ValueError("certificate output-cone planner telemetry is required")
    history_weight = float(output_plan.get("historyWeight", float("nan")))
    repair_work = float(output_plan.get("temporalRepairWork", float("nan")))
    planner_work = float(output_plan.get("plannerWork", float("nan")))
    full_work = float(output_plan.get("fullWork", float("nan")))
    planner_epsilon = float(output_plan.get("epsilon", float("nan")))
    resolved_bound = float(output_plan.get("resolvedRgbBound", float("nan")))
    temporal_stable = bool(output_plan.get("temporalValidationStable", False))
    if not 0.0 <= history_weight <= 1.0:
        raise ValueError("output-cone historyWeight must be in [0,1]")
    if not all(
        value >= 0.0
        for value in (repair_work, planner_work, full_work, planner_epsilon, resolved_bound)
    ):
        raise ValueError("output-cone planner work/bounds must be non-negative")
    if abs(planner_epsilon - float(epsilon)) > 1e-12:
        raise ValueError("output-cone planner epsilon disagrees with experiment epsilon")
    if repair_work > full_work or planner_work > full_work:
        raise ValueError("output-cone planner work exceeds full baseline")

    touched_bytes = int(publication.get("touchedBytes", 0))
    full_bytes = int(publication.get("fullBufferBytes", 0))
    invalidated_pixels = int(temporal.get("invalidatedPixels", 0))
    full_pixels = int(temporal.get("fullFramePixels", 0))
    if not 0 <= touched_bytes <= full_bytes or full_bytes <= 0:
        raise ValueError("invalid Gaussian publication byte accounting")
    if not 0 <= invalidated_pixels <= full_pixels or full_pixels <= 0:
        raise ValueError("invalid temporal pixel accounting")

    revision = int(translation["revision"])
    previous_revision = int(translation["previousRevision"])
    if revision <= previous_revision:
        raise ValueError("world revision must advance monotonically")

    changed_fraction = edited / total_gaussians
    output_planner_graph = {
        "schemaVersion": 1,
        "graph_scope": GAUSSIAN_OUTPUT_GRAPH_VERSION,
        "edit_kind": edit_kind,
        "nodes": [
            {
                "id": "current_frame",
                "work": 0.0,
                "true_change_bound": 0.0,
                "source_bound": 0.0,
            },
            {
                "id": "temporal_history",
                "work": repair_work,
                "true_change_bound": 0.0,
                "source_bound": float(certificate["maximumCurrentRgbBound"]),
            },
        ],
        "edges": [],
        "hard_closure": (
            ["current_frame"]
            if temporal_stable
            else ["current_frame", "temporal_history"]
        ),
        "qois": [
            {
                "name": "resolved-rgb-linf",
                "weights": {"temporal_history": history_weight},
                "epsilon": planner_epsilon,
            }
        ],
        "changed_fraction": changed_fraction,
        "full_work_baseline": full_work,
    }

    work_ledger = {
        "domains": {
            "gaussiansInspected": {
                "incremental": inspected,
                "full": total_gaussians,
                "unit": "gaussians",
            },
            "gaussiansUpdated": {
                "incremental": edited,
                "full": total_gaussians,
                "unit": "gaussians",
            },
            "gpuPublicationBytes": {
                "incremental": touched_bytes,
                "full": full_bytes,
                "unit": "bytes",
            },
            "temporalPixelsInvalidated": {
                "incremental": invalidated_pixels,
                "full": full_pixels,
                "unit": "pixels",
            },
        }
    }

    result: dict[str, Any] = {
        "schemaVersion": 1,
        "scene_id": scene_id,
        "revision_id": f"{previous_revision}->{revision}",
        "git_sha": git_sha,
        "execution_mode": "hybrid-supplied-source-planner-output",
        "selection_mode": (
            "overlay-indexed" if used_overlay else "full-scan-fallback"
        ),
        "overlay_index_valid_after_edit": overlay_valid,
        "graph_scope": GAUSSIAN_OUTPUT_GRAPH_VERSION,
        "graph_version": "gaussian-source-image-history-v1",
        "bound_version": GAUSSIAN_TEMPORAL_BOUND_VERSION,
        "edit_class": f"gaussian-{edit_kind}",
        "edit_kind": edit_kind,
        "coupling_regime": "unclassified-real-scene",
        "before_state": before_state,
        "after_state": after_state,
        "input_format": input_format,
        "detect_changed": True,
        "camera": {
            "width": int(camera["width"]),
            "height": int(camera["height"]),
            "focal_x": float(camera["focalX"]),
            "focal_y": float(camera["focalY"]),
            "center_x": float(camera["centerX"]),
            "center_y": float(camera["centerY"]),
            "near": float(camera["near"]),
            "far": float(camera["far"]),
            "camera_world_position": [float(v) for v in camera_position],
            "world_to_camera": [float(v) for v in world_to_camera],
            "background": [0.0, 0.0, 0.0],
        },
        "epsilon_rgb_linf": float(epsilon),
        # This first vertical slice's graph cardinality is intentionally only
        # source Gaussian records. It is not the final heterogeneous CBRC graph.
        "hard_closure_nodes": edited,
        "candidate_cone_nodes": edited,
        "total_nodes": total_gaussians,
        "work_ledger": work_ledger,
        "output_planner_graph": output_planner_graph,
        "selection_diagnostics": {
            "dirtyRegionsQueried": int(
                translation.get("overlayDirtyRegionsQueried", 0)
            ),
            "baseEntriesVisited": int(
                translation.get("overlayBaseEntriesVisited", 0)
            ),
            "staleBaseEntriesSkipped": int(
                translation.get("overlayStaleBaseEntriesSkipped", 0)
            ),
            "deltaEntriesVisited": int(
                translation.get("overlayDeltaEntriesVisited", 0)
            ),
            "overlayCompacted": bool(
                translation.get("overlayIndexCompacted", False)
            ),
        },
        "production_certificate": {
            "revisionVersion": int(certificate.get("revisionVersion", 0)),
            "maximumCurrentRgbBound": float(
                certificate["maximumCurrentRgbBound"]
            ),
            "affectedPixelRatio": float(certificate["affectedPixelRatio"]),
            "invalidationCoversCertifiedSupport": bool(
                certificate["invalidationCoversCertifiedSupport"]
            ),
            "temporalFullFrameFallback": bool(
                certificate["temporalFullFrameFallback"]
            ),
            "outputConePlanner": {
                "stable": bool(output_plan.get("stable", False)),
                "passes": bool(output_plan.get("passes", False)),
                "temporalValidationStable": temporal_stable,
                "temporalRepairSelected": bool(
                    output_plan.get("temporalRepairSelected", False)
                ),
                "fullRepair": bool(output_plan.get("fullRepair", False)),
                "historyWeight": history_weight,
                "temporalRepairWork": repair_work,
                "plannerWork": planner_work,
                "fullWork": full_work,
                "resolvedRgbBound": resolved_bound,
                "epsilon": planner_epsilon,
            },
        },
    }
    result["native_scalar_work"] = {
        "candidate": planner_work,
        "full": full_work,
        "unit": "temporal-pixels",
        "model_version": HEADLESS_TEMPORAL_PIXEL_COST_MODEL_VERSION,
    }
    if work_cost_model is not None:
        result["work_cost_model"] = work_cost_model
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--translation", type=Path, required=True)
    parser.add_argument("--certificate", type=Path, required=True)
    parser.add_argument("--scene-id", required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--epsilon", type=float, required=True)
    parser.add_argument("--work-cost-model", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    model = (
        load_object(args.work_cost_model)
        if args.work_cost_model is not None
        else None
    )
    result = bind(
        load_object(args.translation),
        load_object(args.certificate),
        scene_id=args.scene_id,
        git_sha=args.git_sha,
        epsilon=args.epsilon,
        work_cost_model=model,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(args.output.suffix + ".tmp")
    tmp.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    tmp.replace(args.output)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
