#!/usr/bin/env python3
"""Expand a MAVEB campaign matrix into immutable per-run JSON configurations."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path
from typing import Any


def stable_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def expand(matrix: dict[str, Any]) -> list[dict[str, Any]]:
    if matrix.get("schemaVersion") != 1:
        raise ValueError("unsupported experiment matrix schema")
    runs = []
    for dataset, method, changed, budget in itertools.product(
        matrix["datasets"],
        matrix["methods"],
        matrix["changedFractions"],
        matrix["resourceBudgets"],
    ):
        seeds = dataset.get("seeds", [42])
        for seed in seeds:
            config = {
                "schemaVersion": 1,
                "campaign": matrix["campaign"],
                "dataset": dataset["id"],
                "datasetKind": dataset["kind"],
                "method": method,
                "changedFraction": changed,
                "resourceBudget": budget,
                "seed": seed,
                "requiredMetrics": matrix["metrics"],
                "gates": matrix["gates"],
            }
            digest = stable_hash(config)
            config["configHash"] = digest
            config["experiment_id"] = (
                f"{matrix['campaign']}__{dataset['id']}__{method}__"
                f"change-{changed:g}__{budget['name']}__seed-{seed}__{digest[:12]}"
            )
            runs.append(config)
    identifiers = [run["experiment_id"] for run in runs]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("experiment matrix produced duplicate IDs")
    return runs


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    matrix = json.loads(args.matrix.read_text())
    runs = expand(matrix)
    for run in runs:
        write_atomic(
            args.output_dir / f"{run['experiment_id']}.json",
            json.dumps(run, indent=2, sort_keys=True) + "\n",
        )
    write_atomic(
        args.output_dir / "index.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "campaign": matrix["campaign"],
                "runCount": len(runs),
                "runs": [run["experiment_id"] for run in runs],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
