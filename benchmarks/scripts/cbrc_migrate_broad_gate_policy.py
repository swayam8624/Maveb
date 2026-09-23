#!/usr/bin/env python3
"""Migrate pre-fix broad gate metadata without touching frozen case inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_cases_sha256(campaign: dict[str, Any]) -> str:
    encoded = json.dumps(
        campaign.get("cases", []),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def policy(campaign: dict[str, Any]) -> dict[str, Any]:
    regimes = sorted(
        {
            str(case.get("coupling_regime", "")).lower()
            for case in campaign.get("cases", [])
        }
    )
    high_required = bool(set(regimes).intersection({"high", "adversarial"}))
    return {
        "require_full_fallback": False,
        "require_high_coupling": high_required,
        "metadata": {
            "fullFallback": "observed-outcome-not-required",
            "highCouplingRequired": high_required,
            "frozenCouplingRegimes": regimes,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--runner-git-sha", required=True)
    args = parser.parse_args()

    campaign_path = args.campaign.resolve()
    freeze_path = args.freeze.resolve()
    campaign = load(campaign_path)
    freeze = load(freeze_path)
    if campaign.get("campaignId") != "maveb-cbrc-broad-benchmark-v1":
        raise SystemExit("refusing gate migration for a non-broad campaign")

    desired = policy(campaign)
    already = (
        campaign.get("require_full_fallback") is False
        and bool(campaign.get("require_high_coupling"))
        == desired["require_high_coupling"]
        and campaign.get("broad_gate_policy") == desired["metadata"]
    )
    migration_path = campaign_path.parent / "BROAD_GATE_POLICY_MIGRATION.json"
    if already:
        print(f"  ✓ broad gate policy already current: {campaign_path}")
        return 0

    before_cases = canonical_cases_sha256(campaign)
    before_campaign_sha = sha256(campaign_path)
    before_freeze_sha = sha256(freeze_path)

    campaign_backup = campaign_path.with_name(
        campaign_path.name + ".pre-gate-policy-migration"
    )
    freeze_backup = freeze_path.with_name(
        freeze_path.name + ".pre-gate-policy-migration"
    )
    if not campaign_backup.exists():
        shutil.copy2(campaign_path, campaign_backup)
    if not freeze_backup.exists():
        shutil.copy2(freeze_path, freeze_backup)

    old = {
        "require_full_fallback": campaign.get("require_full_fallback"),
        "require_high_coupling": campaign.get("require_high_coupling"),
        "broad_gate_policy": campaign.get("broad_gate_policy"),
    }
    campaign["require_full_fallback"] = desired["require_full_fallback"]
    campaign["require_high_coupling"] = desired["require_high_coupling"]
    campaign["broad_gate_policy"] = desired["metadata"]
    write(campaign_path, campaign)

    freeze["broadGatePolicy"] = desired["metadata"]
    freeze["campaignSha256"] = sha256(campaign_path)
    write(freeze_path, freeze)

    after_cases = canonical_cases_sha256(campaign)
    if before_cases != after_cases:
        raise RuntimeError("gate-policy migration unexpectedly changed frozen cases")

    migration = {
        "schemaVersion": 1,
        "artifact": "maveb-cbrc-broad-gate-policy-migration",
        "runnerGitSha": args.runner_git_sha,
        "reason": (
            "Migrate pre-fix broad campaign success-policy metadata. "
            "No frozen case, transform, epsilon, source world, sidecar, result, "
            "certificate, baseline, or measured outcome is modified."
        ),
        "casesSha256": before_cases,
        "oldPolicy": old,
        "newPolicy": {
            "require_full_fallback": desired["require_full_fallback"],
            "require_high_coupling": desired["require_high_coupling"],
            "broad_gate_policy": desired["metadata"],
        },
        "originalCampaignSha256": before_campaign_sha,
        "originalFreezeSha256": before_freeze_sha,
        "migratedCampaignSha256": sha256(campaign_path),
        "migratedFreezeSha256": sha256(freeze_path),
        "campaignBackup": str(campaign_backup),
        "freezeBackup": str(freeze_backup),
    }
    write(migration_path, migration)
    print(f"  ✓ migrated broad gate metadata only: {migration_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
