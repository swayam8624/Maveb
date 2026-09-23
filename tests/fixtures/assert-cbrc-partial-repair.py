#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit(
            "usage: assert-cbrc-partial-repair.py ORACLE BEFORE.ply AFTER.ply"
        )
    oracle = Path(sys.argv[1])
    before = Path(sys.argv[2])
    after = Path(sys.argv[3])

    command = [
        str(oracle),
        "--before", str(before),
        "--after", str(after),
        "--input-format", "ply",
        "--detect-changed",
        "--repair-omit-fraction", "0.5",
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

    assert payload["repairMode"] == "certified-omitted-gaussians-v1", payload
    assert int(payload["changedGaussians"]) == 2, payload
    assert int(payload["repairOmittedGaussians"]) == 1, payload
    assert int(payload["repairAppliedChangedGaussians"]) == 1, payload
    assert int(payload["repairCertificateViolationPixels"]) == 0, payload
    assert actual > 1.0e-8, payload
    assert actual <= bound + 1.0e-12, payload
    assert bound <= float(repair["epsilon"]) + 1.0e-12, payload
    assert bool(payload["repairWithinTolerance"]), payload

    print(
        json.dumps(
            {
                "actual": actual,
                "bound": bound,
                "changed": payload["changedGaussians"],
                "omitted": payload["repairOmittedGaussians"],
                "applied": payload["repairAppliedChangedGaussians"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
