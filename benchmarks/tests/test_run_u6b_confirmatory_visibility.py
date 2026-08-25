#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_u6b_confirmatory_visibility.py"
spec = importlib.util.spec_from_file_location("run_u6b_confirmatory_visibility", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class U6bConfirmatoryRunnerTests(unittest.TestCase):
    def protocol(self) -> dict:
        return {
            "evaluation": {
                "pairedSceneBootstrapReplicates": 2000,
                "pairedSceneBootstrapSeed": 42,
                "positiveConfirmatoryGate": {
                    "candidateVsBaseline": {
                        "minimumMedianAbsolutePrimaryGain": 0.002,
                        "candidateMustBeatBaselineInAtLeastScenes": 4,
                        "paired95IntervalLowerBoundMustExceedZero": True,
                    },
                    "candidateVsShuffled": {
                        "minimumMedianAbsolutePrimaryGain": 0.002,
                        "candidateMustBeatShuffledInAtLeastScenes": 4,
                        "paired95IntervalLowerBoundMustExceedZero": True,
                    },
                    "coverageGuard": {
                        "minimumMedianCandidateToBaselineCoverageRatio": 0.95,
                        "minimumPerSceneCandidateToBaselineCoverageRatio": 0.85,
                    },
                    "overlapErrorGuard": {
                        "candidateMeanAbsoluteDepthErrorMustNotExceedBaselineInAtLeastScenes": 4,
                    },
                },
            }
        }

    @staticmethod
    def summary(primary: float, coverage: float, mae: float) -> dict:
        return {
            "primaryWithin5cmFractionOfFaroValid": primary,
            "coverageFractionMean": coverage,
            "absoluteDepthErrorMeanMetresAcrossTargetMeans": mae,
        }

    def scene_results(
        self,
        *,
        candidate_gain: float = 0.003,
        candidate_vs_shuffled_gain: float = 0.0025,
        candidate_coverage: float = 0.49,
        candidate_mae: float = 0.09,
    ) -> dict:
        result = {}
        for index, scene in enumerate(module.EXPECTED_SCENES):
            baseline_primary = 0.10 + index * 0.001
            candidate_primary = baseline_primary + candidate_gain
            shuffled_primary = candidate_primary - candidate_vs_shuffled_gain
            result[scene] = {
                "methods": {
                    module.BASELINE: {
                        "sceneSummary": self.summary(baseline_primary, 0.50, 0.10),
                    },
                    module.CANDIDATE: {
                        "sceneSummary": self.summary(
                            candidate_primary,
                            candidate_coverage,
                            candidate_mae,
                        ),
                    },
                    module.SHUFFLED: {
                        "sceneSummary": self.summary(shuffled_primary, 0.49, 0.095),
                    },
                }
            }
        return result

    def test_frozen_method_order_and_render_count(self) -> None:
        self.assertEqual(
            module.METHODS,
            (
                "depth-only-fixed-opacity",
                "calibrated-relative-precision-opacity",
                "shuffled-relative-precision-opacity",
            ),
        )
        self.assertEqual(module.TOTAL_RENDERS, 120)

    def test_all_confirmatory_gate_clauses_pass_together(self) -> None:
        result = module.evaluate_gate(self.scene_results(), self.protocol())
        self.assertTrue(result["allGateClausesPassed"])
        self.assertEqual(result["candidateBetterThanBaselineSceneCount"], 5)
        self.assertEqual(result["candidateBetterThanShuffledSceneCount"], 5)
        self.assertEqual(result["candidateMeanAbsoluteDepthErrorNotWorseSceneCount"], 5)
        self.assertTrue(all(result["checks"].values()))

    def test_positive_but_subfloor_effect_is_not_confirmatory(self) -> None:
        result = module.evaluate_gate(
            self.scene_results(
                candidate_gain=0.001,
                candidate_vs_shuffled_gain=0.001,
            ),
            self.protocol(),
        )
        self.assertEqual(result["candidateBetterThanBaselineSceneCount"], 5)
        self.assertEqual(result["candidateBetterThanShuffledSceneCount"], 5)
        self.assertFalse(result["checks"]["candidateVsBaselineMedianEffectFloor"])
        self.assertFalse(result["checks"]["candidateVsShuffledMedianEffectFloor"])
        self.assertFalse(result["allGateClausesPassed"])

    def test_coverage_guard_is_all_clauses_gate(self) -> None:
        result = module.evaluate_gate(
            self.scene_results(candidate_coverage=0.42),
            self.protocol(),
        )
        self.assertFalse(result["checks"]["coverageMedianRatio"])
        self.assertFalse(result["checks"]["coveragePerSceneMinimumRatio"])
        self.assertFalse(result["allGateClausesPassed"])

    def test_authorization_binds_exact_preparation_and_unopened_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "authorization.json"
            payload = {
                "study": module.STUDY_ID,
                "stage": "U6b-confirmatory-render-authorization",
                "status": "authorized-after-frozen-preparation-before-render",
                "protocolSha256": module.PROTOCOL_SHA256,
                "preparationSha256": "prep",
                "renderToolSha256": module.RENDER_TOOL_SHA256,
                "methods": list(module.METHODS),
                "sceneCount": 5,
                "targetViewsPerScene": 8,
                "totalRenderCount": 120,
                "confirmatoryOutcomeObservedBeforeAuthorization": False,
            }
            path.write_text(json.dumps(payload))
            loaded = module.validate_authorization(
                path,
                preparation_sha="prep",
                render_tool_sha=module.RENDER_TOOL_SHA256,
            )
            self.assertEqual(loaded["totalRenderCount"], 120)

            payload["preparationSha256"] = "wrong"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "preparation SHA mismatch"):
                module.validate_authorization(
                    path,
                    preparation_sha="prep",
                    render_tool_sha=module.RENDER_TOOL_SHA256,
                )

            payload["preparationSha256"] = "prep"
            payload["confirmatoryOutcomeObservedBeforeAuthorization"] = True
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "unopened outcome boundary"):
                module.validate_authorization(
                    path,
                    preparation_sha="prep",
                    render_tool_sha=module.RENDER_TOOL_SHA256,
                )


if __name__ == "__main__":
    unittest.main()
