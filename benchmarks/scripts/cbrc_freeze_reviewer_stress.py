#!/usr/bin/env python3
"""Freeze a reviewer-targeted CBRC tolerance-crossover campaign.

This protocol is intentionally separate from the primary broad campaign. It is
pre-specified after external reviewer feedback asking for practical evidence
where a LOCAL repair has measurable non-zero error while remaining certified.

For each deterministically selected real captured world, the exact same physical
edit is replayed across a fixed epsilon ladder. This allows a direct
FULL->LOCAL crossover analysis without choosing cases after observing outcomes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "benchmarks/scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import cbrc_prepare_campaign_v2 as v2
import cbrc_prepare_real_campaign as base


EDIT_FAMILIES = ("translation", "rotation", "uniform-scale", "opacity")
EPSILON_LEVELS_255 = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0)
SEVERITY_PROFILES: tuple[dict[str, Any], ...] = (
    {
        "name": "medium",
        "coupling": "medium",
        "delta_fraction": 0.12,
        "entity_fraction": 0.12,
        "history_weight": 0.90,
        "history_stable": True,
    },
    {
        "name": "strong",
        "coupling": "high",
        "delta_fraction": 0.25,
        "entity_fraction": 0.20,
        "history_weight": 0.97,
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


def stable_scene_rank(dataset_id: str, scene_id: str) -> str:
    return hashlib.sha256(
        f"{dataset_id}\0{scene_id}".encode("utf-8")
    ).hexdigest()


def select_records(
    records: list[dict[str, Any]],
    *,
    scenes_per_dataset: int,
) -> list[dict[str, Any]]:
    if scenes_per_dataset < 1:
        raise ValueError("scenes_per_dataset must be >= 1")

    unique: dict[tuple[str, Path], dict[str, Any]] = {}
    for record in records:
        if record.get("status") != "ready" or not record.get("world"):
            continue
        dataset_id = str(record.get("datasetId", ""))
        world = Path(record["world"]).resolve()
        if not dataset_id:
            continue
        unique.setdefault((dataset_id, world), record)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (dataset_id, _), record in unique.items():
        grouped[dataset_id].append(record)

    selected: list[dict[str, Any]] = []
    for dataset_id in sorted(grouped):
        ranked = sorted(
            grouped[dataset_id],
            key=lambda record: (
                stable_scene_rank(
                    dataset_id,
                    str(record.get("sceneId", Path(record["world"]).stem)),
                ),
                str(record.get("sceneId", "")),
            ),
        )
        selected.extend(ranked[:scenes_per_dataset])
    return selected


def edit_spec(
    *,
    family: str,
    profile: dict[str, Any],
    candidate: base.Candidate,
    entity_id: int,
    family_index: int,
    profile_index: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    delta_fraction = float(profile["delta_fraction"])
    sign = 1 if (family_index + profile_index) % 2 == 0 else -1
    axis_index = (family_index + 2 * profile_index) % 3
    axis = [0.0, 0.0, 0.0]
    axis[axis_index] = 1.0

    metadata: dict[str, Any] = {
        "axis": axis_index,
        "sign": sign,
        "delta_fraction": delta_fraction,
    }

    if family == "translation":
        translation = [
            float(value)
            for value in candidate.entities[entity_id]["translation"]
        ]
        target = list(translation)
        requested = delta_fraction * base.scene_scale(candidate)
        magnitude = max(requested, v2.MINIMUM_EFFECTIVE_TRANSLATION)
        if (
            not math.isfinite(magnitude)
            or magnitude <= v2.WORLD_DIFF_TRANSLATION_THRESHOLD
        ):
            raise ValueError("reviewer stress translation is below effective-edit threshold")
        target[axis_index] += sign * magnitude
        metadata.update(
            {
                "requested_delta_world": requested,
                "applied_delta_world": magnitude,
            }
        )
        return {"kind": "translation", "target": target}, metadata

    if family == "rotation":
        radians = sign * max(0.05, min(0.75, delta_fraction * 1.20))
        metadata["radians"] = radians
        return {"kind": "rotation", "axis": axis, "radians": radians}, metadata

    if family == "uniform-scale":
        fractional_scale = max(0.03, min(0.30, delta_fraction * 0.40))
        factor = 1.0 + sign * fractional_scale
        if factor <= 0.0:
            raise ValueError("reviewer stress uniform scale became non-positive")
        metadata["scale_factor"] = factor
        return {"kind": "uniform-scale", "factor": factor}, metadata

    if family == "opacity":
        logit_delta = sign * max(0.15, min(1.50, delta_fraction * 2.0))
        metadata["opacity_logit_delta"] = logit_delta
        return {"kind": "opacity", "logit_delta": logit_delta}, metadata

    raise ValueError(f"unsupported edit family: {family}")


def build(
    prepared_worlds: dict[str, Any],
    output_dir: Path,
    *,
    scenes_per_dataset: int,
    work_cost_model: Path | None,
    epsilon_levels_255: tuple[float, ...] = EPSILON_LEVELS_255,
) -> tuple[dict[str, Any], dict[str, Any]]:
    records = select_records(
        list(prepared_worlds.get("records", [])),
        scenes_per_dataset=scenes_per_dataset,
    )
    if len(records) < 2:
        raise ValueError("reviewer stress campaign requires at least two prepared worlds")

    roots = [Path(record["world"]).resolve() for record in records]
    candidates, rejected = base.discover(roots, max_depth=0)
    if rejected:
        raise ValueError(
            "reviewer stress selected worlds failed validation: "
            + json.dumps(rejected, sort_keys=True)
        )
    if len(candidates) != len(records):
        raise ValueError(
            f"reviewer stress world mismatch: {len(records)} records, "
            f"{len(candidates)} candidates"
        )

    record_by_world = {
        Path(record["world"]).resolve(): record for record in records
    }
    candidate_by_world = {
        candidate.archive.resolve(): candidate for candidate in candidates
    }

    cases: list[dict[str, Any]] = []
    frozen_inputs: list[dict[str, Any]] = []
    dataset_counts: Counter[str] = Counter()
    family_counts: Counter[str] = Counter()
    profile_counts: Counter[str] = Counter()

    inputs = output_dir / "inputs"
    case_serial = 0

    for record in records:
        source_world = Path(record["world"]).resolve()
        candidate = candidate_by_world[source_world]
        dataset_id = str(record["datasetId"])
        source_scene_id = str(record.get("sceneId", candidate.archive.stem))
        representation = str(record.get("representation", "unknown"))
        camera = base.derive_camera(candidate)

        for profile_index, profile in enumerate(SEVERITY_PROFILES):
            entity_id, owned_count = v2.entity_for_fraction(
                candidate,
                float(profile["entity_fraction"]),
            )
            for family_index, family in enumerate(EDIT_FAMILIES):
                edit, edit_meta = edit_spec(
                    family=family,
                    profile=profile,
                    candidate=candidate,
                    entity_id=entity_id,
                    family_index=family_index,
                    profile_index=profile_index,
                )
                stress_key = (
                    f"{dataset_id}::{source_scene_id}::{profile['name']}::{family}"
                )

                for epsilon_index, epsilon_255 in enumerate(epsilon_levels_255):
                    epsilon = float(epsilon_255) / 255.0
                    case_serial += 1
                    epsilon_label = str(epsilon_255).replace(".", "p")
                    case_id = (
                        f"reviewer--{dataset_id}--{family}--{profile['name']}--"
                        f"{source_scene_id}--eps{epsilon_label}"
                    )
                    case_input_dir = inputs / case_id
                    archive_copy = base.copy_before_state(candidate, case_input_dir)
                    timestamp = (
                        candidate.timestamp
                        + case_serial * 1_000_000
                        + (epsilon_index + 1) * 10_000
                    )

                    matrix_tags = {
                        "protocol": "post-reviewer-tolerance-crossover-v1",
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
                        "matrix_tags": matrix_tags,
                        "revision": {
                            "archive": str(archive_copy),
                            "entity": entity_id,
                            "edit": edit,
                            "timestamp": timestamp,
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
        "campaignId": "maveb-cbrc-reviewer-tolerance-crossover-v1",
        "protocol": "post-reviewer-tolerance-crossover-v1",
        "minimum_revisions": len(cases),
        "minimum_scenes": len(selected_scenes),
        "require_local_success": False,
        "require_full_fallback": False,
        "require_high_coupling": True,
        "epsilonLevels255": list(epsilon_levels_255),
        "severityProfiles": list(SEVERITY_PROFILES),
        "editFamilies": list(EDIT_FAMILIES),
        "datasetCaseCounts": dict(sorted(dataset_counts.items())),
        "editFamilyCaseCounts": dict(sorted(family_counts.items())),
        "severityCaseCounts": dict(sorted(profile_counts.items())),
        "selectedScenes": [
            {"datasetId": dataset, "sceneId": scene}
            for dataset, scene in selected_scenes
        ],
        "cases": cases,
        "freeze_note": (
            "Post-reviewer stress protocol frozen before outcomes are inspected. "
            "Scene selection is deterministic and result-independent. Each stress key "
            "repeats the same physical edit on an independent source-world copy while "
            "only epsilon changes across the fixed tolerance ladder. No case may be "
            "removed or retuned after observing LOCAL/FULL decisions or residuals."
        ),
    }
    provenance = {
        "schemaVersion": 1,
        "artifact": "maveb-cbrc-reviewer-stress-freeze",
        "generator": "benchmarks/scripts/cbrc_freeze_reviewer_stress.py",
        "preparedWorldManifest": str(prepared_worlds.get("outputRoot", "")),
        "selectedWorldCount": len(records),
        "selectedScenes": campaign["selectedScenes"],
        "selectionRule": "lowest sha256(dataset_id\\0scene_id) per dataset",
        "scenesPerDataset": scenes_per_dataset,
        "epsilonLevels255": list(epsilon_levels_255),
        "severityProfiles": list(SEVERITY_PROFILES),
        "editFamilies": list(EDIT_FAMILIES),
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
        description="Freeze reviewer-targeted non-zero residual/crossover stress cases"
    )
    result.add_argument("--worlds", type=Path, required=True)
    result.add_argument("--output-dir", type=Path, required=True)
    result.add_argument("--scenes-per-dataset", type=int, default=2)
    result.add_argument("--work-cost-model", type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.scenes_per_dataset < 1:
        raise SystemExit("--scenes-per-dataset must be >= 1")
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
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
