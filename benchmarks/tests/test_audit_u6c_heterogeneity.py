#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_u6c_heterogeneity.py"
spec = importlib.util.spec_from_file_location("audit_u6c_heterogeneity", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def target(index: int, value: float) -> dict:
    return {
        "targetIndex": index,
        "within5cmFractionOfFaroValid": value,
    }


def method_payload(primary: float, coverage: float, mae: float, p95: float, within10: float) -> dict:
    return {
        "sceneSummary": {
            "primaryWithin5cmFractionOfFaroValid": primary,
            "coverageFractionMean": coverage,
            "absoluteDepthErrorMeanMetresAcrossTargetMeans": mae,
            "absoluteDepthErrorP95MetresAcrossTargetP95": p95,
            "within10cmFractionOfFaroValidMean": within10,
        },
        "targets": [target(index, primary + (index - 3.5) * 0.001) for index in range(8)],
    }


def fixture_result() -> dict:
    baseline_values = [0.40, 0.45, 0.50, 0.55, 0.60]
    candidate_deltas = [0.01, 0.0, -0.001, 0.002, 0.10]
    shuffled_deltas = [0.005, 0.0, -0.002, 0.003, 0.09]
    scenes: dict[str, dict] = {}
    per_scene: dict[str, dict] = {}
    for scene, baseline, delta_baseline, delta_shuffled in zip(
        module.EXPECTED_SCENES,
        baseline_values,
        candidate_deltas,
        shuffled_deltas,
        strict=True,
    ):
        candidate = baseline + delta_baseline
        shuffled = candidate - delta_shuffled
        scenes[scene] = {
            "methods": {
                module.BASELINE: method_payload(baseline, 0.95, 0.20, 0.50, 0.60),
                module.CANDIDATE: method_payload(candidate, 0.94, 0.19, 0.48, 0.61),
                module.SHUFFLED: method_payload(shuffled, 0.945, 0.195, 0.49, 0.605),
            }
        }
        per_scene[scene] = {
            "candidateMinusBaseline": delta_baseline,
            "candidateMinusShuffled": delta_shuffled,
        }
    return {
        "study": module.PARENT_STUDY_ID,
        "status": "completed-confirmatory-gate-not-passed",
        "renderCount": 120,
        "methodOrder": list(module.METHODS),
        "confirmatoryGate": {
            "allGateClausesPassed": False,
            "perScene": per_scene,
        },
        "scenes": scenes,
    }


class U6cHeterogeneityAuditTests(unittest.TestCase):
    def test_summary_is_descriptive_and_preserves_negative_parent(self) -> None:
        payload = module.summarize_result(fixture_result())
        self.assertEqual(payload["study"], module.STUDY_ID)
        self.assertFalse(payload["parentAllGateClausesPassed"])
        self.assertEqual(payload["sceneCount"], 5)
        self.assertEqual(payload["heterogeneity"]["candidateMinusBaselineMaximum"], 0.10)
        self.assertEqual(payload["heterogeneity"]["candidateMinusBaselineMinimum"], -0.001)
        self.assertEqual(
            payload["heterogeneity"]["rankingByCandidateMinusBaseline"][0]["scene"],
            module.EXPECTED_SCENES[4],
        )
        integrity = payload["integrity"]
        self.assertFalse(integrity["rerendered"])
        self.assertFalse(integrity["confirmatoryGateRecomputed"])
        self.assertFalse(integrity["transferRuleFitOrTuned"])

    def test_target_level_counts_use_only_frozen_target_records(self) -> None:
        result = fixture_result()
        first_scene = result["scenes"][module.EXPECTED_SCENES[0]]
        candidate_targets = first_scene["methods"][module.CANDIDATE]["targets"]
        baseline_targets = first_scene["methods"][module.BASELINE]["targets"]
        candidate_targets[0]["within5cmFractionOfFaroValid"] = 0.20
        baseline_targets[0]["within5cmFractionOfFaroValid"] = 0.30
        payload = module.summarize_result(result)
        first = payload["scenes"][0]["targetLevelPrimary"]
        self.assertEqual(first["candidateBetterThanBaselineTargetCount"], 7)

    def test_rejects_parent_that_was_not_negative_null(self) -> None:
        result = fixture_result()
        result["confirmatoryGate"]["allGateClausesPassed"] = True
        with self.assertRaisesRegex(ValueError, "negative/null"):
            module.summarize_result(result)

    def test_rejects_scene_delta_disagreement_with_frozen_gate(self) -> None:
        result = fixture_result()
        result["confirmatoryGate"]["perScene"][module.EXPECTED_SCENES[0]][
            "candidateMinusBaseline"
        ] = 0.123
        with self.assertRaisesRegex(ValueError, "candidate-minus-baseline mismatch"):
            module.summarize_result(result)


if __name__ == "__main__":
    unittest.main()
