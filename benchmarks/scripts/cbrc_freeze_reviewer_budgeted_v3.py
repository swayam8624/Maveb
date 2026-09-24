#!/usr/bin/env python3
"""Freeze reviewer-v3 certificate-budgeted partial-repair cases.

Reviewer-v2 used a fixed omitted-Gaussian fraction. Its frozen outcome showed
that every such residual certificate exceeded epsilon. Reviewer-v3 therefore
changes the algorithm, not the observed cases: approximation is allocated a
fixed fraction of the *remaining* certified RGB tolerance after the production
planner's resolved bound. The oracle then chooses the largest deterministic
nested omitted subset that fits that absolute residual budget.

The v2 campaign remains immutable and is not rewritten by this script.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

import cbrc_freeze_reviewer_stress as v2


DEFAULT_RESIDUAL_BUDGET_FRACTION = 0.50
PROTOCOL = "post-reviewer-budgeted-partial-repair-v3"
CAMPAIGN_ID = "maveb-cbrc-reviewer-budgeted-partial-repair-v3"


def convert_v2_to_v3(
    campaign: dict[str, Any],
    provenance: dict[str, Any],
    *,
    residual_budget_fraction: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not 0.0 < residual_budget_fraction < 1.0:
        raise ValueError("residual_budget_fraction must lie strictly inside (0,1)")

    campaign = copy.deepcopy(campaign)
    provenance = copy.deepcopy(provenance)

    campaign["campaignId"] = CAMPAIGN_ID
    campaign["protocol"] = PROTOCOL
    campaign["repairResidualBudgetFraction"] = residual_budget_fraction

    converted_profiles = []
    for profile in campaign.get("severityProfiles", []):
        profile = dict(profile)
        profile.pop("repair_omit_fraction", None)
        profile["repair_residual_budget_fraction"] = residual_budget_fraction
        converted_profiles.append(profile)
    campaign["severityProfiles"] = converted_profiles

    for case in campaign.get("cases", []):
        case.pop("reviewer_repair_omit_fraction", None)
        case["reviewer_repair_residual_budget_fraction"] = residual_budget_fraction
        matrix = case.get("matrix_tags")
        if isinstance(matrix, dict):
            matrix.pop("repair_omit_fraction", None)
            matrix["repair_residual_budget_fraction"] = residual_budget_fraction
            matrix["protocol"] = PROTOCOL

    campaign["freeze_note"] = (
        "Reviewer-v3 is frozen before v3 outcomes are inspected. Scene selection, "
        "physical edits, epsilon ladder, and deterministic source-world copies match "
        "the reviewer stress design. Unlike v2's fixed omitted-Gaussian percentage, "
        "v3 allocates a predeclared fraction of the remaining certified RGB tolerance "
        "after the production planner's resolved bound. The oracle selects the largest "
        "deterministic nested omitted subset whose conservative residual certificate "
        "fits that budget. No case may be removed or retuned after observing outcomes."
    )

    provenance["artifact"] = "maveb-cbrc-reviewer-budgeted-stress-freeze"
    provenance["generator"] = "benchmarks/scripts/cbrc_freeze_reviewer_budgeted_v3.py"
    provenance["protocol"] = PROTOCOL
    provenance["repairResidualBudgetFraction"] = residual_budget_fraction

    converted_frozen_inputs = []
    for item in provenance.get("frozen_inputs", []):
        item = dict(item)
        item.pop("repair_omit_fraction", None)
        item["repair_residual_budget_fraction"] = residual_budget_fraction
        matrix = item.get("matrix")
        if isinstance(matrix, dict):
            matrix = dict(matrix)
            matrix.pop("repair_omit_fraction", None)
            matrix["repair_residual_budget_fraction"] = residual_budget_fraction
            matrix["protocol"] = PROTOCOL
            item["matrix"] = matrix
        converted_frozen_inputs.append(item)
    provenance["frozen_inputs"] = converted_frozen_inputs

    converted_provenance_profiles = []
    for profile in provenance.get("severityProfiles", []):
        profile = dict(profile)
        profile.pop("repair_omit_fraction", None)
        profile["repair_residual_budget_fraction"] = residual_budget_fraction
        converted_provenance_profiles.append(profile)
    provenance["severityProfiles"] = converted_provenance_profiles

    return campaign, provenance


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Freeze reviewer-v3 certificate-budgeted residual cases"
    )
    result.add_argument("--worlds", type=Path, required=True)
    result.add_argument("--output-dir", type=Path, required=True)
    result.add_argument("--scenes-per-dataset", type=int, default=1)
    result.add_argument("--work-cost-model", type=Path)
    result.add_argument(
        "--residual-budget-fraction",
        type=float,
        default=DEFAULT_RESIDUAL_BUDGET_FRACTION,
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.scenes_per_dataset < 1:
        raise SystemExit("--scenes-per-dataset must be >= 1")
    if not 0.0 < args.residual_budget_fraction < 1.0:
        raise SystemExit("--residual-budget-fraction must lie strictly inside (0,1)")
    if args.work_cost_model is not None and not args.work_cost_model.is_file():
        raise SystemExit(f"work cost model not found: {args.work_cost_model}")

    worlds_path = args.worlds.resolve()
    prepared_worlds = v2.load(worlds_path)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    campaign, provenance = v2.build(
        prepared_worlds,
        output,
        scenes_per_dataset=args.scenes_per_dataset,
        work_cost_model=args.work_cost_model,
    )
    campaign, provenance = convert_v2_to_v3(
        campaign,
        provenance,
        residual_budget_fraction=args.residual_budget_fraction,
    )

    campaign_path = output / "reviewer-stress-v3-campaign.json"
    freeze_path = output / "REVIEWER_STRESS_V3_FREEZE.json"
    v2.write(campaign_path, campaign)

    provenance["preparedWorldManifest"] = str(worlds_path)
    provenance["preparedWorldManifestSha256"] = v2.base.sha256(worlds_path)
    provenance["campaignSha256"] = v2.base.sha256(campaign_path)
    v2.write(freeze_path, provenance)

    print(
        json.dumps(
            {
                "campaign": str(campaign_path),
                "freeze": str(freeze_path),
                "selectedWorlds": provenance["selectedWorldCount"],
                "cases": len(campaign["cases"]),
                "datasets": campaign["datasetCaseCounts"],
                "epsilonLevels255": campaign["epsilonLevels255"],
                "residualBudgetFraction": args.residual_budget_fraction,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
