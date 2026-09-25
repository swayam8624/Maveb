#!/usr/bin/env python3
"""Freeze confirmatory CBRC opacity-delta breadth campaign v6.

v2 deliberately omitted whole changed Gaussians and established that this coarse
stress was too severe: every frozen case remained certificate-safe but replay
selected FULL after the omitted-repair residual was added.

v6 is a confirmatory breadth protocol frozen after the v5 mechanism result and
before any v6 outcomes are inspected. It changes no algorithm, edit magnitude,
certificate threshold, epsilon value, residual amplitude, locality profile, or
control family from v5. The only intentional change is independent-scene breadth:
five deterministically ranked prepared worlds per dataset are required so the
primary analysis can aggregate at scene level rather than treating parameter
sweeps as independent samples. v3/v4/v5 remain immutable.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "benchmarks/scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import cbrc_freeze_reviewer_stress as v2
import cbrc_prepare_campaign_v2 as campaign_v2
import cbrc_prepare_real_campaign as base

EXPECTED_DATASETS = (
    "3rscan",
    "arkitscenes",
    "bonn-rgbd-dynamic",
    "graphdeco-pretrained-3dgs",
)
EDIT_FAMILIES = ("opacity", "translation")
EPSILON_LEVELS_255 = (1.0, 2.0, 4.0, 8.0, 16.0, 32.0)
RESIDUAL_SCALES = (0.0, 1.0 / 4096.0, 1.0 / 1024.0, 1.0 / 256.0)

SEVERITY_PROFILES: tuple[dict[str, Any], ...] = (
    {
        "name": "smallest-entity",
        "coupling": "low",
        "delta_fraction": 0.06,
        "entity_fraction": 0.0001,
        "history_weight": 0.90,
        "history_stable": True,
    },
    {
        "name": "tiny-local",
        "coupling": "low",
        "delta_fraction": 0.06,
        "entity_fraction": 0.01,
        "history_weight": 0.90,
        "history_stable": True,
    },
    {
        "name": "local",
        "coupling": "medium",
        "delta_fraction": 0.06,
        "entity_fraction": 0.03,
        "history_weight": 0.90,
        "history_stable": True,
    },
    {
        "name": "broad-control",
        "coupling": "medium",
        "delta_fraction": 0.06,
        "entity_fraction": 0.12,
        "history_weight": 0.90,
        "history_stable": True,
    },
)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def residual_label(scale: float) -> str:
    if scale == 0.0:
        return "exact"
    denominator = round(1.0 / scale)
    return f"r1of{denominator}"


def build(
    prepared_worlds: dict[str, Any],
    output_dir: Path,
    *,
    scenes_per_dataset: int,
    work_cost_model: Path | None,
    epsilon_levels_255: tuple[float, ...] = EPSILON_LEVELS_255,
    residual_scales: tuple[float, ...] = RESIDUAL_SCALES,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not residual_scales or residual_scales[0] != 0.0:
        raise ValueError("v6 residual ladder must start with exact repair scale 0")
    if any(scale < 0.0 or scale > 1.0 for scale in residual_scales):
        raise ValueError("v6 residual scales must lie in [0,1]")
    if len(set(residual_scales)) != len(residual_scales):
        raise ValueError("v6 residual scales must be unique")

    if scenes_per_dataset != 5:
        raise ValueError("confirmatory v6 is frozen at exactly 5 scenes per dataset")
    records = v2.select_records(
        list(prepared_worlds.get("records", [])),
        scenes_per_dataset=scenes_per_dataset,
    )
    selected_counts = Counter(str(record["datasetId"]) for record in records)
    expected = set(EXPECTED_DATASETS)
    observed = set(selected_counts)
    if observed != expected:
        raise ValueError(
            "confirmatory v6 must preserve the four v5 dataset families exactly; "
            + json.dumps(
                {
                    "expected": sorted(expected),
                    "observed": sorted(observed),
                    "missing": sorted(expected - observed),
                    "unexpected": sorted(observed - expected),
                },
                sort_keys=True,
            )
        )
    incomplete = {
        dataset: selected_counts.get(dataset, 0)
        for dataset in EXPECTED_DATASETS
        if selected_counts.get(dataset, 0) != scenes_per_dataset
    }
    if incomplete:
        raise ValueError(
            "confirmatory v6 requires exactly five independent scenes from each v5 dataset; "
            + json.dumps(incomplete, sort_keys=True)
        )

    roots = [Path(record["world"]).resolve() for record in records]
    candidates, rejected = base.discover(roots, max_depth=0)
    if rejected:
        raise ValueError(
            "reviewer v6 selected worlds failed validation: "
            + json.dumps(rejected, sort_keys=True)
        )
    if len(candidates) != len(records):
        raise ValueError(
            f"reviewer v6 world mismatch: {len(records)} records, "
            f"{len(candidates)} candidates"
        )
    candidate_by_world = {
        candidate.archive.resolve(): candidate for candidate in candidates
    }

    cases: list[dict[str, Any]] = []
    frozen_inputs: list[dict[str, Any]] = []
    dataset_counts: Counter[str] = Counter()
    family_counts: Counter[str] = Counter()
    profile_counts: Counter[str] = Counter()
    residual_counts: Counter[str] = Counter()

    inputs = output_dir / "inputs"
    stress_serial = 0

    for record in records:
        source_world = Path(record["world"]).resolve()
        candidate = candidate_by_world[source_world]
        dataset_id = str(record["datasetId"])
        source_scene_id = str(record.get("sceneId", candidate.archive.stem))
        representation = str(record.get("representation", "unknown"))
        camera = base.derive_camera(candidate)

        for profile_index, profile in enumerate(SEVERITY_PROFILES):
            entity_id, owned_count = campaign_v2.entity_for_fraction(
                candidate,
                float(profile["entity_fraction"]),
            )
            for family_index, family in enumerate(EDIT_FAMILIES):
                edit, edit_meta = v2.edit_spec(
                    family=family,
                    profile=profile,
                    candidate=candidate,
                    entity_id=entity_id,
                    family_index=family_index,
                    # Hold edit direction/sign constant across locality profiles.
                    # The selected entity-size target remains a controlled v5 factor.
                    profile_index=0,
                )
                stress_serial += 1
                fixed_timestamp = candidate.timestamp + stress_serial * 1_000_000

                for residual_scale in residual_scales:
                    rlabel = residual_label(residual_scale)
                    stress_key = (
                        f"{dataset_id}::{source_scene_id}::{profile['name']}::"
                        f"{family}::{rlabel}"
                    )

                    for epsilon_255 in epsilon_levels_255:
                        epsilon = float(epsilon_255) / 255.0
                        epsilon_label = str(epsilon_255).replace(".", "p")
                        case_id = (
                            f"reviewerv6--{dataset_id}--{family}--{profile['name']}--"
                            f"{source_scene_id}--{rlabel}--eps{epsilon_label}"
                        )
                        case_input_dir = inputs / case_id
                        archive_copy = base.copy_before_state(
                            candidate, case_input_dir, materialize=False
                        )

                        matrix_tags = {
                            "protocol": "confirmatory-opacity-delta-v6",
                            "stress_key": stress_key,
                            "dataset_id": dataset_id,
                            "source_scene_id": source_scene_id,
                            "representation": representation,
                            "severity_profile": profile["name"],
                            "coupling_regime": profile["coupling"],
                            "entity_fraction_target": float(profile["entity_fraction"]),
                            "selected_entity_fraction": owned_count / candidate.gaussian_count,
                            "history_weight": float(profile["history_weight"]),
                            "history_stable": bool(profile["history_stable"]),
                            "repair_omit_fraction": 0.0,
                            "repair_residual_scale": float(residual_scale),
                            "repair_residual_label": rlabel,
                            "edit_family": family,
                            "epsilon_255": float(epsilon_255),
                            "epsilon": epsilon,
                            "natural_change_pair": record.get("naturalChangePair"),
                            **edit_meta,
                        }
                        case: dict[str, Any] = {
                            "id": case_id,
                            "scene_id": f"{dataset_id}::{source_scene_id}",
                            "dataset_id": dataset_id,
                            "source_scene_id": source_scene_id,
                            "representation": representation,
                            "epsilon": epsilon,
                            "coupling_regime": str(profile["coupling"]),
                            "edit_family": family,
                            "edit_class": f"gaussian-{family}",
                            "reviewer_repair_residual_scale": float(residual_scale),
                            "matrix_tags": matrix_tags,
                            "revision": {
                                "archive": str(archive_copy),
                                "entity": entity_id,
                                "edit": edit,
                                "timestamp": fixed_timestamp,
                                "history_stable": bool(profile["history_stable"]),
                                "history_weight": float(profile["history_weight"]),
                                "camera": camera,
                            },
                        }
                        if work_cost_model is not None:
                            case["work_cost_model"] = str(work_cost_model.resolve())
                        cases.append(case)
                        dataset_counts[dataset_id] += 1
                        family_counts[family] += 1
                        profile_counts[str(profile["name"])] += 1
                        residual_counts[rlabel] += 1

                        frozen_inputs.append(
                            {
                                "case_id": case_id,
                                "stress_key": stress_key,
                                "source_archive": str(candidate.archive),
                                "source_revision": candidate.revision,
                                "source_archive_sha256": base.sha256(candidate.archive),
                                "source_gaussian_sha256": base.sha256(candidate.gaussian_sidecar),
                                "source_ownership_sha256": base.sha256(candidate.ownership_sidecar),
                                "gaussian_count": candidate.gaussian_count,
                                "selected_entity": entity_id,
                                "selected_entity_gaussians": owned_count,
                                "selected_fraction": owned_count / candidate.gaussian_count,
                                "dataset_id": dataset_id,
                                "source_scene_id": source_scene_id,
                                "representation": representation,
                                "severity_profile": profile["name"],
                                "edit_family": family,
                                "edit_parameters": edit,
                                "repair_omit_fraction": 0.0,
                                "repair_residual_scale": float(residual_scale),
                                "repair_residual_label": rlabel,
                                "epsilon_255": float(epsilon_255),
                                "epsilon": epsilon,
                                "matrix": matrix_tags,
                            }
                        )

    selected_scenes = sorted(
        {
            (str(record["datasetId"]), str(record.get("sceneId", "")))
            for record in records
        }
    )
    campaign = {
        "schemaVersion": 1,
        "campaignId": "maveb-cbrc-confirmatory-opacity-delta-v6",
        "protocol": "confirmatory-opacity-delta-v6",
        "minimum_revisions": len(cases),
        "minimum_scenes": len(selected_scenes),
        "require_local_success": False,
        "require_full_fallback": False,
        "require_high_coupling": False,
        "epsilonLevels255": list(epsilon_levels_255),
        "residualScales": list(residual_scales),
        "severityProfiles": list(SEVERITY_PROFILES),
        "editFamilies": list(EDIT_FAMILIES),
        "certificateExperiment": {
            "primaryEditFamily": "opacity",
            "controlEditFamily": "translation",
            "primaryExpectedCertificateMode": "opacity-delta-lipschitz-v1",
            "controlExpectedCertificateMode": "opacity-envelope-union-v1",
            "outcomeBlindFreeze": True,
            "confirmationOf": "maveb-cbrc-reviewer-opacity-delta-v5",
            "algorithmChangedFromV5": False,
            "targetScenesPerDataset": 5,
            "expectedDatasets": list(EXPECTED_DATASETS),
            "primaryUnitOfAnalysis": "scene",
        },
        "datasetCaseCounts": dict(sorted(dataset_counts.items())),
        "editFamilyCaseCounts": dict(sorted(family_counts.items())),
        "severityCaseCounts": dict(sorted(profile_counts.items())),
        "residualCaseCounts": dict(sorted(residual_counts.items())),
        "selectedScenes": [
            {"datasetId": dataset, "sceneId": scene}
            for dataset, scene in selected_scenes
        ],
        "cases": cases,
        "freeze_note": (
            "Confirmatory v6 is frozen before any v6 outcomes are inspected. "
            "It repeats the complete v5 opacity-vs-translation protocol unchanged on exactly "
            "five deterministically ranked scenes per dataset. The primary unit of analysis "
            "is the scene; pooled parameter cases are secondary evidence only. No v6 scene, "
            "epsilon, residual amplitude, locality profile, edit family, or failed outcome may "
            "be deleted or retuned after execution begins. v3/v4/v5 remain immutable."
        )
    }
    provenance = {
        "schemaVersion": 1,
        "artifact": "maveb-cbrc-confirmatory-opacity-delta-v6-freeze",
        "generator": "benchmarks/scripts/cbrc_freeze_confirmatory_v6.py",
        "preparedWorldManifest": str(prepared_worlds.get("outputRoot", "")),
        "selectedWorldCount": len(records),
        "selectedScenes": campaign["selectedScenes"],
        "selectionRule": (
            "same deterministic SHA-256 scene ranking as v2-v5; first five ready scenes "
            "per dataset, frozen before v6 outcomes"
        ),
        "scenesPerDataset": scenes_per_dataset,
        "epsilonLevels255": list(epsilon_levels_255),
        "residualScales": list(residual_scales),
        "severityProfiles": list(SEVERITY_PROFILES),
        "editFamilies": list(EDIT_FAMILIES),
        "expectedDatasets": list(EXPECTED_DATASETS),
        "certificateExperiment": campaign["certificateExperiment"],
        "caseCount": len(cases),
        "frozen_inputs": frozen_inputs,
        "work_cost_model": (
            None
            if work_cost_model is None
            else {
                "path": str(work_cost_model.resolve()),
                "sha256": base.sha256(work_cost_model),
            }
        ),
    }
    return campaign, provenance


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Freeze confirmatory opacity-delta breadth v6 cases"
    )
    result.add_argument("--worlds", type=Path, required=True)
    result.add_argument("--output-dir", type=Path, required=True)
    result.add_argument("--scenes-per-dataset", type=int, default=5)
    result.add_argument("--work-cost-model", type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.scenes_per_dataset != 5:
        raise SystemExit("confirmatory v6 is frozen at --scenes-per-dataset 5")
    if args.work_cost_model is not None and not args.work_cost_model.is_file():
        raise SystemExit(f"work cost model not found: {args.work_cost_model}")

    worlds_path = args.worlds.resolve()
    prepared_worlds = load(worlds_path)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    campaign, provenance = build(
        prepared_worlds,
        output,
        scenes_per_dataset=args.scenes_per_dataset,
        work_cost_model=args.work_cost_model,
    )
    campaign_path = output / "reviewer-stress-campaign.json"
    freeze_path = output / "REVIEWER_STRESS_FREEZE.json"
    write(campaign_path, campaign)
    provenance["preparedWorldManifest"] = str(worlds_path)
    provenance["preparedWorldManifestSha256"] = base.sha256(worlds_path)
    provenance["campaignSha256"] = base.sha256(campaign_path)
    write(freeze_path, provenance)

    print(
        json.dumps(
            {
                "campaign": str(campaign_path),
                "freeze": str(freeze_path),
                "selectedWorlds": provenance["selectedWorldCount"],
                "cases": len(campaign["cases"]),
                "datasets": campaign["datasetCaseCounts"],
                "epsilonLevels255": campaign["epsilonLevels255"],
                "residualScales": campaign["residualScales"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
