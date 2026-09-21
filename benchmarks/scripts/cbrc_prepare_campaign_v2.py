#!/usr/bin/env python3
"""Freeze a paper-scale CBRC campaign from immutable real MAVEB worlds.

Campaign-v2 deliberately freezes a broad edit matrix *before* outcomes are read.
It expands the five-case pilot to 15 deterministic revisions per scene, spanning
edit magnitude, selected-entity size, temporal history weight, epsilon, axis,
and stable/unstable history. Each case gets an independent copy of its starting
world so execution order cannot contaminate results.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import cbrc_prepare_real_campaign as base


TEMPLATES: tuple[dict[str, Any], ...] = (
    {"name":"tiny-a","coupling":"low","delta":0.0025,"eps":2/255,"stable":True,"weight":0.25,"entity_fraction":0.01,"axis":0,"sign":1},
    {"name":"tiny-b","coupling":"low","delta":0.0050,"eps":1/255,"stable":True,"weight":0.50,"entity_fraction":0.02,"axis":1,"sign":-1},
    {"name":"local-a","coupling":"low","delta":0.0100,"eps":1/255,"stable":True,"weight":0.75,"entity_fraction":0.03,"axis":2,"sign":1},
    {"name":"local-b","coupling":"low","delta":0.0200,"eps":0.5/255,"stable":True,"weight":0.90,"entity_fraction":0.05,"axis":0,"sign":-1},
    {"name":"local-c","coupling":"medium","delta":0.0400,"eps":1/255,"stable":True,"weight":0.95,"entity_fraction":0.08,"axis":1,"sign":1},
    {"name":"medium-a","coupling":"medium","delta":0.0600,"eps":1/255,"stable":True,"weight":0.50,"entity_fraction":0.03,"axis":2,"sign":-1},
    {"name":"medium-b","coupling":"medium","delta":0.0900,"eps":0.5/255,"stable":True,"weight":0.75,"entity_fraction":0.08,"axis":0,"sign":1},
    {"name":"medium-c","coupling":"medium","delta":0.1200,"eps":1/255,"stable":True,"weight":0.97,"entity_fraction":0.12,"axis":1,"sign":-1},
    {"name":"high-a","coupling":"high","delta":0.1800,"eps":1/255,"stable":True,"weight":0.90,"entity_fraction":0.15,"axis":2,"sign":1},
    {"name":"high-b","coupling":"high","delta":0.2500,"eps":0.5/255,"stable":True,"weight":0.97,"entity_fraction":0.20,"axis":0,"sign":-1},
    {"name":"high-unstable","coupling":"high","delta":0.1800,"eps":1/255,"stable":False,"weight":0.90,"entity_fraction":0.08,"axis":1,"sign":1},
    {"name":"adv-a","coupling":"adversarial","delta":0.3500,"eps":0.5/255,"stable":True,"weight":0.97,"entity_fraction":0.25,"axis":2,"sign":-1},
    {"name":"adv-unstable-a","coupling":"adversarial","delta":0.3500,"eps":1/255,"stable":False,"weight":0.90,"entity_fraction":0.15,"axis":0,"sign":1},
    {"name":"adv-unstable-b","coupling":"adversarial","delta":0.5000,"eps":0.5/255,"stable":False,"weight":0.97,"entity_fraction":0.25,"axis":1,"sign":-1},
    {"name":"adv-unstable-c","coupling":"adversarial","delta":0.6500,"eps":0.25/255,"stable":False,"weight":0.99,"entity_fraction":0.35,"axis":2,"sign":1},
)


def entity_for_fraction(candidate: base.Candidate, target: float) -> tuple[int, int]:
    counts = Counter(owner for owner in candidate.owners if owner in candidate.entities)
    if not counts:
        raise ValueError(f"{candidate.archive} has no current owned Gaussians")
    viable = [(entity, count) for entity, count in counts.items() if count >= 4]
    if not viable:
        viable = list(counts.items())
    entity, count = min(
        viable,
        key=lambda item: (
            abs(item[1] / candidate.gaussian_count - target),
            item[1] / candidate.gaussian_count > 0.50,
            item[0],
        ),
    )
    return int(entity), int(count)


def build(
    candidates: list[base.Candidate],
    output_dir: Path,
    *,
    cases_per_scene: int,
    work_cost_model: Path | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not 1 <= cases_per_scene <= len(TEMPLATES):
        raise ValueError(f"cases_per_scene must be in [1,{len(TEMPLATES)}]")
    if len(candidates) < 2:
        raise ValueError("campaign-v2 requires at least two real scenes")

    inputs = output_dir / "inputs"
    cases: list[dict[str, Any]] = []
    frozen: list[dict[str, Any]] = []

    for scene_index, candidate in enumerate(candidates):
        scale = base.scene_scale(candidate)
        camera = base.derive_camera(candidate)
        for template_index, template in enumerate(TEMPLATES[:cases_per_scene]):
            entity_id, owned_count = entity_for_fraction(
                candidate, float(template["entity_fraction"])
            )
            translation = [
                float(v) for v in candidate.entities[entity_id]["translation"]
            ]
            target = list(translation)
            axis = int(template["axis"])
            target[axis] += (
                int(template["sign"]) * float(template["delta"]) * scale
            )

            case_id = (
                f"v2-{candidate.archive.stem}-{template_index:02d}-"
                f"{template['name']}"
            )
            archive_copy = base.copy_before_state(candidate, inputs / case_id)
            case: dict[str, Any] = {
                "id": case_id,
                "scene_id": candidate.archive.stem,
                "epsilon": float(template["eps"]),
                "coupling_regime": str(template["coupling"]),
                "edit_class": "gaussian",
                "matrix_tags": {
                    "delta_fraction": float(template["delta"]),
                    "entity_fraction_target": float(template["entity_fraction"]),
                    "history_weight": float(template["weight"]),
                    "history_stable": bool(template["stable"]),
                    "axis": axis,
                    "sign": int(template["sign"]),
                },
                "revision": {
                    "archive": str(archive_copy),
                    "entity": entity_id,
                    "target": target,
                    "timestamp": (
                        candidate.timestamp
                        + (scene_index + 1) * 100_000_000
                        + (template_index + 1) * 1_000_000
                    ),
                    "history_stable": bool(template["stable"]),
                    "history_weight": float(template["weight"]),
                    "camera": camera,
                },
            }
            if work_cost_model is not None:
                case["work_cost_model"] = str(work_cost_model.resolve())
            cases.append(case)
            frozen.append(
                {
                    "case_id": case_id,
                    "source_archive": str(candidate.archive),
                    "source_revision": candidate.revision,
                    "source_archive_sha256": base.sha256(candidate.archive),
                    "source_gaussian_sha256": base.sha256(candidate.gaussian_sidecar),
                    "source_ownership_sha256": base.sha256(candidate.ownership_sidecar),
                    "gaussian_count": candidate.gaussian_count,
                    "selected_entity": entity_id,
                    "selected_entity_gaussians": owned_count,
                    "selected_fraction": owned_count / candidate.gaussian_count,
                    "scene_scale": scale,
                    "matrix": case["matrix_tags"],
                    "epsilon": case["epsilon"],
                }
            )

    scenes = {case["scene_id"] for case in cases}
    campaign = {
        "schemaVersion": 2,
        "campaignId": "cbrc-public-real-v2",
        "minimum_revisions": len(cases),
        "minimum_scenes": len(scenes),
        "require_local_success": True,
        "require_full_fallback": True,
        "require_high_coupling": True,
        "cases": cases,
        "freeze_note": (
            "Paper-scale v2 matrix frozen before execution. Do not remove cases, "
            "retune epsilon, transforms, entity choices, temporal stability, or "
            "history weights after inspecting outcomes."
        ),
    }
    provenance = {
        "schemaVersion": 2,
        "artifact": "maveb-cbrc-public-real-v2-freeze",
        "generator": "benchmarks/scripts/cbrc_prepare_campaign_v2.py",
        "candidate_count": len(candidates),
        "scene_count": len(scenes),
        "case_count": len(cases),
        "cases_per_scene": cases_per_scene,
        "template_count_available": len(TEMPLATES),
        "frozen_inputs": frozen,
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--world-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cases-per-scene", type=int, default=15)
    parser.add_argument("--work-cost-model", type=Path)
    args = parser.parse_args()

    if args.work_cost_model is not None and not args.work_cost_model.is_file():
        parser.error(f"work cost model not found: {args.work_cost_model}")

    candidates, rejected = base.discover([args.world_root], max_depth=3)
    if not candidates:
        raise SystemExit("no complete real MAVEB worlds found for campaign-v2")

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    campaign, provenance = build(
        candidates,
        output,
        cases_per_scene=args.cases_per_scene,
        work_cost_model=args.work_cost_model,
    )
    campaign_path = output / "campaign-v2.json"
    freeze_path = output / "campaign-v2-freeze.json"
    campaign_path.write_text(json.dumps(campaign, indent=2, sort_keys=True) + "\n")
    provenance["campaign_sha256"] = base.sha256(campaign_path)
    provenance["rejected_worlds"] = rejected
    freeze_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    print(campaign_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
