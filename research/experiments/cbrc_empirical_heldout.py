#!/usr/bin/env python3
"""Held-out empirical locality baseline for campaign-v2.

This deliberately tests a common heuristic: infer a single changed-fraction
threshold from earlier examples, then choose LOCAL below the threshold and FULL
above it. The split is fixed by SHA-256(case_id) before outcomes are read.

The heuristic is trained only on its training partition. Its held-out LOCAL
safety is judged by the independently measured full-reference residual of the
candidate local repair, not by whether CBRC happened to choose LOCAL or FULL.
CBRC disagreement is reported separately because CBRC may conservatively fall
back for certification/stability reasons even when one sampled residual happens
to be within epsilon.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from pathlib import Path
from typing import Any


SAFETY_GROUND_TRUTH = "independent candidate full-reference residual <= epsilon"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def split(case_id: str) -> str:
    value = int(hashlib.sha256(case_id.encode()).hexdigest()[:8], 16)
    return "train" if value % 3 == 0 else "heldout"


def candidate_measurement(row: dict[str, Any]) -> tuple[float, float, float]:
    qois = row.get("qois")
    if not isinstance(qois, dict) or "rgb_linf" not in qois:
        raise ValueError("campaign row requires qois.rgb_linf")
    epsilon = float(qois["rgb_linf"]["epsilon"])

    diagnostics = row.get("candidateDiagnostics")
    if not isinstance(diagnostics, dict):
        raise ValueError("campaign row requires candidateDiagnostics")
    if "candidateActualRgbError" not in diagnostics:
        raise ValueError(
            "campaign row requires candidateDiagnostics.candidateActualRgbError"
        )
    if "candidateRgbBound" not in diagnostics:
        raise ValueError("campaign row requires candidateDiagnostics.candidateRgbBound")

    actual = float(diagnostics["candidateActualRgbError"])
    bound = float(diagnostics["candidateRgbBound"])
    if min(epsilon, actual, bound) < 0.0:
        raise ValueError("epsilon/candidate residual/bound must be non-negative")
    return epsilon, actual, bound


def candidate_observed_safe(row: dict[str, Any]) -> bool:
    epsilon, actual, _ = candidate_measurement(row)
    return actual <= epsilon + 1e-12


def choose_threshold(train: list[dict[str, Any]]) -> float:
    fractions = sorted({float(row["changed_fraction"]) for row in train})
    candidates = [0.0] + fractions + [1.0]
    best = None
    for threshold in candidates:
        tp = tn = fp = fn = 0
        for row in train:
            predicted_local = float(row["changed_fraction"]) <= threshold
            actual_local_safe = candidate_observed_safe(row)
            if predicted_local and actual_local_safe:
                tp += 1
            elif not predicted_local and not actual_local_safe:
                tn += 1
            elif predicted_local and not actual_local_safe:
                fp += 1
            else:
                fn += 1
        tpr = tp / max(tp + fn, 1)
        tnr = tn / max(tn + fp, 1)
        balanced = 0.5 * (tpr + tnr)
        # Safety first: minimize observed unsafe LOCAL decisions, then maximize
        # balanced accuracy, then choose the more conservative threshold.
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
            raise ValueError(
                "campaign rows must include case_id for empirical held-out split"
            )
        # Validate the independent residual evidence up front, before splitting.
        candidate_measurement(row)
        enriched.append({**row, "_split": split(case_id)})

    train = [row for row in enriched if row["_split"] == "train"]
    heldout = [row for row in enriched if row["_split"] == "heldout"]
    if not train or not heldout:
        raise ValueError("empirical held-out split produced empty partition")

    threshold = choose_threshold(train)
    unsafe = []
    cbrc_rejected = []
    bound_exceeds = []
    decisions = []
    work_ratios = []
    correct = 0
    predicted_local_count = 0

    for row in heldout:
        predicted_local = float(row["changed_fraction"]) <= threshold
        observed_safe = candidate_observed_safe(row)
        cbrc_local = not bool(row["fallback_full"])
        epsilon, candidate_actual, candidate_bound = candidate_measurement(row)

        unsafe_false_local = predicted_local and not observed_safe
        cbrc_rejected_local = predicted_local and not cbrc_local
        bound_exceeds_epsilon = predicted_local and candidate_bound > epsilon + 1e-12

        if predicted_local:
            predicted_local_count += 1
        if unsafe_false_local:
            unsafe.append(str(row["case_id"]))
        if cbrc_rejected_local:
            cbrc_rejected.append(str(row["case_id"]))
        if bound_exceeds_epsilon:
            bound_exceeds.append(str(row["case_id"]))

        correct += int(predicted_local == observed_safe)

        diagnostics = row["candidateDiagnostics"]
        candidate_work = float(diagnostics.get("candidateWork", row["planner_work"]))
        full = float(row["full_work"])
        selected = candidate_work if predicted_local else full
        ratio = selected / full if full > 0 else 1.0
        work_ratios.append(ratio)

        decisions.append(
            {
                "case_id": row["case_id"],
                "scene_id": row.get("scene_id"),
                "changed_fraction": row["changed_fraction"],
                "predicted_local": predicted_local,
                "candidate_observed_safe": observed_safe,
                "candidate_actual_rgb_error": candidate_actual,
                "candidate_rgb_bound": candidate_bound,
                "epsilon": epsilon,
                "cbrc_local": cbrc_local,
                "unsafe_false_local": unsafe_false_local,
                "cbrc_rejected_local": cbrc_rejected_local,
                "candidate_bound_exceeds_epsilon": bound_exceeds_epsilon,
                "work_ratio_full": ratio,
            }
        )

    unsafe_rate = len(unsafe) / len(heldout)
    conditional_unsafe_rate = (
        len(unsafe) / predicted_local_count if predicted_local_count else 0.0
    )
    cbrc_rejected_rate = len(cbrc_rejected) / len(heldout)

    return {
        "schemaVersion": 2,
        "artifact": "cbrc-empirical-heldout-baseline",
        "splitRule": "sha256(case_id)[0:8] mod 3 == 0 => train; otherwise heldout",
        "model": (
            "single changed-fraction threshold fitted on training candidate "
            "full-reference tolerance outcomes"
        ),
        "safetyGroundTruth": SAFETY_GROUND_TRUTH,
        "trainCases": len(train),
        "heldoutCases": len(heldout),
        "learnedThreshold": threshold,
        "heldoutPredictedLocalCases": predicted_local_count,
        "heldoutDecisionAccuracy": correct / len(heldout),
        "heldoutObservedSafetyAccuracy": correct / len(heldout),
        "heldoutUnsafeFalseLocalCases": unsafe,
        "heldoutUnsafeFalseLocalRate": unsafe_rate,
        "heldoutConditionalUnsafeFalseLocalRate": conditional_unsafe_rate,
        "heldoutCBRCRejectedLocalCases": cbrc_rejected,
        "heldoutCBRCRejectedLocalRate": cbrc_rejected_rate,
        "heldoutCandidateBoundExceedsEpsilonLocalCases": bound_exceeds,
        "heldoutMedianWorkRatioFull": statistics.median(work_ratios),
        "decisions": decisions,
        "interpretation": (
            "Unsafe false-LOCAL means the heuristic selected LOCAL and the "
            "independently measured candidate full-reference residual exceeded "
            "epsilon. CBRC-rejected LOCAL choices are reported separately and are "
            "not automatically called unsafe, because certification can be "
            "conservative or can reject a candidate for stability/coverage reasons. "
            "This empirical heuristic has no certificate."
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
