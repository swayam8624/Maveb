#!/usr/bin/env python3
"""Run one manifest-bound CBRC Gaussian full-reference replay.

Exit semantics of the C++ oracle:
  0: source-edit certificate holds and its raw effect bound <= epsilon
  3: source-edit certificate holds but the raw edit-effect bound > epsilon
  4: source-edit certificate violation (fatal)
  other: execution/configuration failure

For production output-cone manifests, code 3 is not itself a reason to fall
back: an intended edit may be much larger than epsilon while the selected
repair still reproduces FULL-after within tolerance. In that path the final
decision uses the production output plan plus independently measured
post-repair residual evidence. Legacy fixtures without a production plan keep
the older code-3 => FULL behavior.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.cbrc.work import WorkCostModel


def require_number(data: dict[str, Any], key: str, *, positive: bool = False) -> float:
    value = float(data[key])
    if positive and value <= 0:
        raise ValueError(f"{key} must be positive")
    if not positive and value < 0:
        raise ValueError(f"{key} must be non-negative")
    return value


def resolve_scalar_work(manifest: dict[str, Any]) -> tuple[float, float, str, str]:
    model_data = manifest.get("work_cost_model")
    ledger = manifest.get("work_ledger", {})
    if model_data is not None:
        if not isinstance(ledger, dict):
            raise ValueError("work_ledger must be an object")
        domains = ledger.get("domains", ledger)
        if not isinstance(domains, dict) or not domains:
            raise ValueError(
                "work_cost_model requires non-empty work_ledger domains"
            )
        model = WorkCostModel.from_mapping(model_data)
        candidate = model.estimate(domains, field="incremental")
        full = model.estimate(domains, field="full")
        if full <= 0.0:
            raise ValueError("frozen work-cost model produced non-positive full work")
        return candidate, full, model.version, model.cost_unit

    native = manifest.get("native_scalar_work")
    if isinstance(native, dict):
        candidate = float(native["candidate"])
        full = float(native["full"])
        version = str(native.get("model_version", "")).strip()
        unit = str(native.get("unit", "")).strip()
        if candidate < 0.0 or full <= 0.0 or candidate > full:
            raise ValueError("native scalar work must satisfy 0 <= candidate <= full")
        if not version or not unit:
            raise ValueError("native scalar work requires model_version and unit")
        return candidate, full, version, unit

    # Compatibility path for early fixtures only.
    candidate = require_number(manifest, "candidate_work")
    full = require_number(manifest, "full_work", positive=True)
    return candidate, full, "explicit-manifest-fixture", "arbitrary"


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
    changed = manifest.get("changed_indices")
    detect_changed = bool(manifest.get("detect_changed", False))
    has_explicit_changed = isinstance(changed, list) and bool(changed)
    if has_explicit_changed == detect_changed:
        raise ValueError(
            "specify exactly one of non-empty changed_indices or detect_changed=true"
        )

    before_state = manifest.get("before_state", manifest.get("before_ply"))
    after_state = manifest.get("after_state", manifest.get("after_ply"))
    if not before_state or not after_state:
        raise ValueError("before_state and after_state are required")
    input_format = str(manifest.get("input_format", "ply"))
    if input_format not in ("ply", "aether-bin"):
        raise ValueError("input_format must be ply or aether-bin")

    command = [
        str(binary),
        "--before", str(before_state),
        "--after", str(after_state),
        "--input-format", input_format,
    ]
    if detect_changed:
        command.append("--detect-changed")
    else:
        command.extend(
            ["--changed", ",".join(str(int(i)) for i in changed)]
        )
    spatial_output = manifest.get("spatial_output")
    if spatial_output:
        command.extend(["--spatial-output", str(spatial_output)])
    visual_output_dir = manifest.get("visual_output_dir")
    if visual_output_dir:
        command.extend(["--visual-output-dir", str(visual_output_dir)])
    repair_omit_fraction = float(manifest.get("repair_omit_fraction", 0.0))
    repair_residual_budget = float(manifest.get("repair_residual_budget", 0.0))
    if repair_omit_fraction > 0.0 and repair_residual_budget > 0.0:
        raise ValueError(
            "repair_omit_fraction and repair_residual_budget are mutually exclusive"
        )
    if repair_omit_fraction > 0.0:
        command.extend(["--repair-omit-fraction", str(repair_omit_fraction)])
    if repair_residual_budget > 0.0:
        command.extend(["--repair-residual-budget", str(repair_residual_budget)])

    command.extend([
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
    ])
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

    candidate_work, full_work, work_model_version, work_cost_unit = (
        resolve_scalar_work(manifest)
    )
    total_nodes = int(manifest["total_nodes"])
    hard_nodes = int(manifest["hard_closure_nodes"])
    candidate_nodes = int(manifest["candidate_cone_nodes"])
    if total_nodes <= 0 or not (0 <= hard_nodes <= candidate_nodes <= total_nodes):
        raise ValueError("invalid hard/candidate/total node cardinalities")

    source_qoi = oracle["qois"]["rgb_linf"]

    production = manifest.get("production_certificate")
    selected_qoi = source_qoi
    source_effect_only = False
    if production is not None:
        production_bound = float(production["maximumCurrentRgbBound"])
        oracle_bound = float(source_qoi["certified_bound"])
        agreement_tolerance = max(
            1e-8, 1e-6 * max(abs(production_bound), abs(oracle_bound), 1.0)
        )
        if abs(production_bound - oracle_bound) > agreement_tolerance:
            raise RuntimeError(
                "production/offline certificate bound disagreement: "
                f"{production_bound} vs {oracle_bound}"
            )
        expected_changed_fraction = hard_nodes / total_nodes
        actual_changed_fraction = float(oracle["changedFraction"])
        if abs(expected_changed_fraction - actual_changed_fraction) > 1e-12:
            raise RuntimeError(
                "production/offline changed-fraction disagreement: "
                f"{expected_changed_fraction} vs {actual_changed_fraction}"
            )

        output_plan = production.get("outputConePlanner")
        if not isinstance(output_plan, dict):
            raise ValueError("production certificate requires outputConePlanner")
        plan_stable = bool(output_plan.get("stable", False))
        plan_passes = bool(output_plan.get("passes", False))
        plan_full = bool(output_plan.get("fullRepair", False))
        temporal_repair = bool(output_plan.get("temporalRepairSelected", False))
        invalidation_covers = bool(
            production.get("invalidationCoversCertifiedSupport", False)
        )

        repair_qois = oracle.get("repair_qois")
        if not isinstance(repair_qois, dict) or "rgb_linf" not in repair_qois:
            raise ValueError("oracle is missing post-repair residual evidence")
        repair_qoi = repair_qois["rgb_linf"]
        repair_actual = float(repair_qoi["measured_full_reference_error"])
        repair_bound = float(repair_qoi["certified_bound"])
        repair_epsilon = float(repair_qoi["epsilon"])
        if repair_actual > repair_bound + 1e-12:
            raise RuntimeError(
                "post-repair full-reference residual exceeded its certified bound"
            )
        if abs(repair_epsilon - float(source_qoi["epsilon"])) > 1e-12:
            raise RuntimeError("source and post-repair oracle epsilon disagree")

        if not plan_full and (not plan_stable or not plan_passes):
            raise RuntimeError(
                "production planner rejected local repair without selecting FULL"
            )
        if not plan_full and (not temporal_repair or not invalidation_covers):
            raise RuntimeError(
                "local production plan lacks exact temporal repair coverage"
            )

        resolved_bound = float(output_plan.get("resolvedRgbBound", 0.0))
        selected_qoi = {
            "epsilon": repair_epsilon,
            "certified_bound": resolved_bound + repair_bound,
            "measured_full_reference_error": repair_actual,
        }
        source_effect_only = True
        fallback = (
            plan_full
            or selected_qoi["certified_bound"] > selected_qoi["epsilon"] + 1e-12
            or repair_actual > selected_qoi["epsilon"] + 1e-12
        )
    else:
        fallback = returncode == 3 or not bool(oracle.get("withinTolerance", False))

    if fallback:
        # The selected execution becomes the full rebuild. Its stale-error
        # certificate relative to itself is exactly zero. Preserve the rejected
        # local candidate below for crossover analysis.
        qoi = {
            "epsilon": float(selected_qoi["epsilon"]),
            "certified_bound": 0.0,
            "measured_full_reference_error": 0.0,
        }
        cone_nodes = total_nodes
        planner_work = full_work
    else:
        qoi = {
            "epsilon": float(selected_qoi["epsilon"]),
            "certified_bound": float(selected_qoi["certified_bound"]),
            "measured_full_reference_error": float(
                selected_qoi["measured_full_reference_error"]
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
        "execution_mode": str(
            manifest.get("execution_mode", "planner-selected-cone")
        ),
        "graph_scope": str(manifest.get("graph_scope", "heterogeneous-world")),
        "selection_mode": str(manifest.get("selection_mode", "unspecified")),
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
        "work_cost_model_version": work_model_version,
        "work_cost_unit": work_cost_unit,
        "qois": {"rgb_linf": qoi},
        "work_ledger": manifest.get("work_ledger", {}),
        "spatial_evidence": str(manifest.get("spatial_output", "")),
        "candidateDiagnostics": {
            "candidateConeNodes": candidate_nodes,
            "candidateWork": candidate_work,
            "candidateRgbBound": float(selected_qoi["certified_bound"]),
            "candidateActualRgbError": float(
                selected_qoi["measured_full_reference_error"]
            ),
            "candidateWithinTolerance": (
                float(selected_qoi["certified_bound"])
                <= float(selected_qoi["epsilon"]) + 1e-12
            ),
            "sourceEditRgbBound": float(source_qoi["certified_bound"]),
            "sourceEditActualRgbError": float(
                source_qoi["measured_full_reference_error"]
            ),
            "sourceEditWithinTolerance": bool(
                oracle.get("withinTolerance", False)
            ),
            "postRepairResidualBound": float(
                oracle.get("repair_qois", {})
                .get("rgb_linf", {})
                .get("certified_bound", selected_qoi["certified_bound"])
            ),
            "postRepairActualRgbError": float(
                oracle.get("repair_qois", {})
                .get("rgb_linf", {})
                .get(
                    "measured_full_reference_error",
                    selected_qoi["measured_full_reference_error"],
                )
            ),
            "productionResolvedRgbBound": float(
                manifest.get("production_certificate", {})
                .get("outputConePlanner", {})
                .get("resolvedRgbBound", 0.0)
            ),
            "sourceEffectOnlyOracleReturnCode": bool(source_effect_only and returncode == 3),
            "affectedPixelFraction": float(oracle["affectedPixelFraction"]),
            "effectivity": float(oracle["effectivity"]),
            "certificateViolationPixels": int(
                oracle["certificateViolationPixels"]
            ),
            "repairMode": str(oracle.get("repairMode", "exact-changed-support-v1")),
            "repairOmitFractionRequested": float(
                oracle.get("repairOmitFractionRequested", 0.0)
            ),
            "repairOmittedGaussians": int(oracle.get("repairOmittedGaussians", 0)),
            "repairAppliedChangedGaussians": int(
                oracle.get("repairAppliedChangedGaussians", oracle.get("changedGaussians", 0))
            ),
            "repairCertificateViolationPixels": int(
                oracle.get("repairCertificateViolationPixels", 0)
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
