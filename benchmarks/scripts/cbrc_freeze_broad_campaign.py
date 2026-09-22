#!/usr/bin/env python3
"""Freeze one cross-dataset CBRC campaign before outcomes are inspected."""

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

import cbrc_prepare_campaign_v2 as v2
import cbrc_prepare_real_campaign as base


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


EDIT_FAMILIES = ("translation", "rotation", "uniform-scale", "opacity")


def apply_edit_family(case: dict[str, Any], template_index: int) -> str:
    kind = EDIT_FAMILIES[template_index % len(EDIT_FAMILIES)]
    matrix = case.setdefault("matrix_tags", {})
    delta = float(matrix.get("delta_fraction", 0.01))
    sign = 1 if int(matrix.get("sign", 1)) >= 0 else -1
    axis_index = int(matrix.get("axis", 0)) % 3
    axis = [0.0, 0.0, 0.0]
    axis[axis_index] = 1.0

    revision = case["revision"]
    if kind == "translation":
        revision["edit"] = {
            "kind": "translation",
            "target": list(revision["target"]),
        }
        magnitude = float(matrix["applied_delta_world"])
    elif kind == "rotation":
        radians = sign * max(0.03, min(0.75, delta * 1.20))
        revision.pop("target", None)
        revision["edit"] = {
            "kind": "rotation",
            "axis": axis,
            "radians": radians,
        }
        magnitude = abs(radians)
    elif kind == "uniform-scale":
        fractional_scale = max(0.02, min(0.30, delta * 0.40))
        factor = 1.0 + sign * fractional_scale
        if factor <= 0.0:
            raise ValueError("frozen uniform-scale template became non-positive")
        revision.pop("target", None)
        revision["edit"] = {
            "kind": "uniform-scale",
            "factor": factor,
        }
        magnitude = abs(factor - 1.0)
    else:
        logit_delta = sign * max(0.10, min(1.50, delta * 2.0))
        revision.pop("target", None)
        revision["edit"] = {
            "kind": "opacity",
            "logit_delta": logit_delta,
        }
        magnitude = abs(logit_delta)

    case["edit_family"] = kind
    case["edit_class"] = f"gaussian-{kind}"
    matrix["edit_family"] = kind
    matrix["edit_magnitude"] = magnitude
    matrix["edit_parameters"] = revision["edit"]
    return kind


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Freeze broad multi-dataset CBRC campaign")
    p.add_argument("--worlds", type=Path, required=True, help="BROAD_WORLDS.json")
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--cases-per-scene", type=int, default=15)
    p.add_argument("--work-cost-model", type=Path)
    p.add_argument("--dataset", action="append", default=[])
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    manifest = load(args.worlds.resolve())
    selected = set(args.dataset)
    records = [
        record
        for record in manifest.get("records", [])
        if record.get("status") == "ready"
        and record.get("world")
        and (not selected or record.get("datasetId") in selected)
    ]
    # One physical world path can appear more than once when multiple 3RScan change pairs
    # share the same reference scan. Freeze each world exactly once.
    unique: dict[Path, dict[str, Any]] = {}
    for record in records:
        unique.setdefault(Path(record["world"]).resolve(), record)
    records = list(unique.values())
    if len(records) < 2:
        raise SystemExit("broad campaign needs at least two prepared worlds")

    roots = [Path(record["world"]).resolve() for record in records]
    candidates, rejected = base.discover(roots, max_depth=0)
    if rejected:
        raise SystemExit("prepared worlds failed validation: " + json.dumps(rejected, indent=2))
    if len(candidates) != len(records):
        raise SystemExit(
            f"prepared-world mismatch: {len(records)} records but {len(candidates)} valid worlds"
        )

    by_world = {Path(record["world"]).resolve(): record for record in records}
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    campaign, provenance = v2.build(
        candidates,
        output,
        cases_per_scene=args.cases_per_scene,
        work_cost_model=args.work_cost_model.resolve() if args.work_cost_model else None,
    )

    frozen_by_case = {
        item["case_id"]: item for item in provenance.get("frozen_inputs", [])
    }
    edit_family_counts: Counter[str] = Counter()
    for case_index, case in enumerate(campaign["cases"]):
        family = apply_edit_family(case, case_index % args.cases_per_scene)
        edit_family_counts[family] += 1
        frozen = frozen_by_case[case["id"]]
        frozen["edit_family"] = family
        frozen["edit_parameters"] = case["revision"]["edit"]
        frozen["matrix"] = case["matrix_tags"]
    renamed: dict[str, str] = {}
    dataset_counts: Counter[str] = Counter()
    representation_counts: Counter[str] = Counter()
    for case in campaign["cases"]:
        old_id = case["id"]
        frozen = frozen_by_case[old_id]
        source_world = Path(frozen["source_archive"]).resolve()
        record = by_world[source_world]
        dataset_id = str(record["datasetId"])
        representation = str(record.get("representation", "unknown"))
        source_scene = str(record.get("sceneId", case["scene_id"]))
        edit_family = str(case["edit_family"])
        new_id = f"{dataset_id}--{edit_family}--{old_id}"
        renamed[old_id] = new_id
        case["id"] = new_id
        case["scene_id"] = f"{dataset_id}::{source_scene}"
        case["dataset_id"] = dataset_id
        case["source_scene_id"] = source_scene
        case["representation"] = representation
        case.setdefault("matrix_tags", {})
        case["matrix_tags"].update(
            {
                "dataset_id": dataset_id,
                "source_scene_id": source_scene,
                "representation": representation,
                "natural_change_pair": record.get("naturalChangePair"),
            }
        )
        dataset_counts[dataset_id] += 1
        representation_counts[representation] += 1

    for frozen in provenance.get("frozen_inputs", []):
        old_id = frozen["case_id"]
        source_world = Path(frozen["source_archive"]).resolve()
        record = by_world[source_world]
        frozen["case_id"] = renamed[old_id]
        frozen["dataset_id"] = record["datasetId"]
        frozen["source_scene_id"] = record.get("sceneId")
        frozen["representation"] = record.get("representation")
        frozen["natural_change_pair"] = record.get("naturalChangePair")

    campaign["schemaVersion"] = max(4, int(campaign.get("schemaVersion", 0)))
    campaign["campaignId"] = "maveb-cbrc-broad-benchmark-v1"
    campaign["minimum_scenes"] = len(records)
    campaign["minimum_revisions"] = len(campaign["cases"])
    campaign["dataset_case_counts"] = dict(sorted(dataset_counts.items()))
    campaign["representation_case_counts"] = dict(sorted(representation_counts.items()))
    campaign["edit_family_case_counts"] = dict(sorted(edit_family_counts.items()))
    campaign["freeze_note"] = (
        "Cross-dataset campaign frozen before reading outcomes. One implementation commit, "
        "one work calibration, and one deterministic multi-edit transformation of the v2.1 template matrix are applied "
        "without per-dataset epsilon/threshold retuning. Failed and FULL cases remain evidence."
    )

    provenance.update(
        {
            "schemaVersion": max(4, int(provenance.get("schemaVersion", 0))),
            "artifact": "maveb-cbrc-broad-benchmark-freeze",
            "preparedWorldManifest": str(args.worlds.resolve()),
            "preparedWorldManifestSha256": base.sha256(args.worlds.resolve()),
            "preparedWorldCount": len(records),
            "datasetCaseCounts": dict(sorted(dataset_counts.items())),
            "representationCaseCounts": dict(sorted(representation_counts.items())),
            "casesPerScene": args.cases_per_scene,
            "algorithmicEditFamilies": list(EDIT_FAMILIES),
            "editFamilyCaseCounts": dict(sorted(edit_family_counts.items())),
            "blockedEditFamiliesRemainExcluded": [
                "removal",
                "insertion",
            ],
        }
    )

    campaign_path = output / "broad-campaign.json"
    freeze_path = output / "BROAD_CAMPAIGN_FREEZE.json"
    write(campaign_path, campaign)
    provenance["campaignSha256"] = base.sha256(campaign_path)
    write(freeze_path, provenance)
    print(
        json.dumps(
            {
                "campaign": str(campaign_path),
                "freeze": str(freeze_path),
                "worlds": len(records),
                "cases": len(campaign["cases"]),
                "datasets": dict(sorted(dataset_counts.items())),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
