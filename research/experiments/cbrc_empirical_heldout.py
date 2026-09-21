#!/usr/bin/env python3
"""Held-out empirical locality baseline for campaign-v2.

This deliberately tests a common heuristic: infer a single changed-fraction
threshold from earlier examples, then choose LOCAL below the threshold and FULL
above it. The split is fixed by SHA-256(case_id) before outcomes are read.

Training may use LOCAL/FULL outcomes only on its training partition. Held-out
safety is judged against the frozen production/oracle decision; false LOCAL
choices are counted as unsafe heuristic decisions. CBRC remains independently
certified and is not fitted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def split(case_id: str) -> str:
    value = int(hashlib.sha256(case_id.encode()).hexdigest()[:8], 16)
    return "train" if value % 3 == 0 else "heldout"


def choose_threshold(train: list[dict[str, Any]]) -> float:
    fractions = sorted({float(row["changed_fraction"]) for row in train})
    candidates = [0.0] + fractions + [1.0]
    best = None
    for threshold in candidates:
        tp = tn = fp = fn = 0
        for row in train:
            predicted_local = float(row["changed_fraction"]) <= threshold
            actual_local = not bool(row["fallback_full"])
            if predicted_local and actual_local:
                tp += 1
            elif not predicted_local and not actual_local:
                tn += 1
            elif predicted_local and not actual_local:
                fp += 1
            else:
                fn += 1
        tpr = tp / max(tp + fn, 1)
        tnr = tn / max(tn + fp, 1)
        balanced = 0.5 * (tpr + tnr)
        score = (fp, -balanced, threshold)
        if best is None or score < best[0]:
            best = (score, threshold)
    assert best is not None
    return float(best[1])


def evaluate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    enriched = []
    for row in rows:
        case_id = str(row.get("case_id", "")).strip()
        if not case_id:
            raise ValueError("campaign rows must include case_id for empirical held-out split")
        enriched.append({**row, "_split": split(case_id)})

    train = [row for row in enriched if row["_split"] == "train"]
    heldout = [row for row in enriched if row["_split"] == "heldout"]
    if not train or not heldout:
        raise ValueError("empirical held-out split produced empty partition")

    threshold = choose_threshold(train)
    unsafe = []
    decisions = []
    work_ratios = []
    correct = 0
    for row in heldout:
        predicted_local = float(row["changed_fraction"]) <= threshold
        actual_local = not bool(row["fallback_full"])
        if predicted_local and not actual_local:
            unsafe.append(str(row["case_id"]))
        correct += int(predicted_local == actual_local)
        candidate = float(row.get("candidateDiagnostics", {}).get("candidateWork", row["planner_work"]))
        full = float(row["full_work"])
        selected = candidate if predicted_local else full
        ratio = selected / full if full > 0 else 1.0
        work_ratios.append(ratio)
        decisions.append(
            {
                "case_id": row["case_id"],
                "scene_id": row.get("scene_id"),
                "changed_fraction": row["changed_fraction"],
                "predicted_local": predicted_local,
                "cbrc_local": actual_local,
                "unsafe_false_local": predicted_local and not actual_local,
                "work_ratio_full": ratio,
            }
        )

    return {
        "schemaVersion": 1,
        "artifact": "cbrc-empirical-heldout-baseline",
        "splitRule": "sha256(case_id)[0:8] mod 3 == 0 => train; otherwise heldout",
        "model": "single changed-fraction threshold fitted on training LOCAL/FULL outcomes",
        "trainCases": len(train),
        "heldoutCases": len(heldout),
        "learnedThreshold": threshold,
        "heldoutDecisionAccuracy": correct / len(heldout),
        "heldoutUnsafeFalseLocalCases": unsafe,
        "heldoutUnsafeFalseLocalRate": len(unsafe) / len(heldout),
        "heldoutMedianWorkRatioFull": statistics.median(work_ratios),
        "decisions": decisions,
        "interpretation": (
            "This is an intentionally simple empirical locality heuristic with a fixed held-out "
            "protocol. A false-LOCAL decision is unsafe without CBRC certification."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(load_jsonl(args.rows))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
