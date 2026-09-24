#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit(
            "usage: assert-cbrc-budgeted-partial-repair.py ORACLE BEFORE.ply AFTER.ply"
        )

    oracle = Path(sys.argv[1])
    before = Path(sys.argv[2])
    after = Path(sys.argv[3])
    requested_budget = 10.0

    command = [
        str(oracle),
        "--before", str(before),
        "--after", str(after),
        "--input-format", "ply",
        "--detect-changed",
        "--repair-residual-budget", str(requested_budget),
        "--epsilon", "10.0",
        "--width", "96",
        "--height", "64",
        "--focal-x", "80",
        "--focal-y", "80",
        "--center-x", "48",
        "--center-y", "32",
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise AssertionError(
            f"oracle failed with {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    payload = json.loads(result.stdout)
    repair = payload["repair_qois"]["rgb_linf"]
    actual = float(repair["measured_full_reference_error"])
    bound = float(repair["certified_bound"])
    applied_budget = float(payload["repairResidualBudget"])

    assert payload["repairMode"] == "certified-budgeted-omitted-gaussians-v2", payload
    assert int(payload["changedGaussians"]) == 2, payload
    assert int(payload["repairOmittedGaussians"]) == 1, payload
    assert int(payload["repairAppliedChangedGaussians"]) == 1, payload
    assert int(payload["repairCertificateViolationPixels"]) == 0, payload
    assert float(payload["repairResidualBudgetRequested"]) == requested_budget, payload
    assert 0.0 < applied_budget < requested_budget, payload
    assert actual > 1.0e-8, payload
    assert actual <= bound + 1.0e-12, payload
    assert bound <= requested_budget + 1.0e-12, payload
    assert bool(payload["repairWithinTolerance"]), payload

    print(
        json.dumps(
            {
                "actual": actual,
                "bound": bound,
                "requestedBudget": requested_budget,
                "appliedBudget": applied_budget,
                "changed": payload["changedGaussians"],
                "omitted": payload["repairOmittedGaussians"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
