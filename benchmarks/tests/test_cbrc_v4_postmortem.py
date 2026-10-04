from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


postmortem = load_module(
    "cbrc_v4_postmortem",
    "research/analysis/cbrc_v4_postmortem.py",
)


class ReviewerV4PostmortemTests(unittest.TestCase):
    def test_isolates_residual_mode_from_profile_and_epsilon(self):
        rows = []
        cases = []
        profiles = ("smallest-entity", "broad-control")
        residuals = (0.0, 1.0 / 1024.0)
        epsilons = (1.0, 32.0)

        with tempfile.TemporaryDirectory() as temporary:
            campaign_dir = Path(temporary)
            serial = 0
            for profile in profiles:
                for residual in residuals:
                    for epsilon255 in epsilons:
                        serial += 1
                        case_id = f"case-{serial}"
                        fallback = residual > 0.0
                        cases.append(
                            {
                                "id": case_id,
                                "scene_id": "dataset::scene",
                                "dataset_id": "dataset",
                                "source_scene_id": "scene",
                                "representation": "test",
                                "edit_family": "translation",
                                "coupling_regime": "low",
                                "epsilon": epsilon255 / 255.0,
                                "matrix_tags": {
                                    "severity_profile": profile,
                                    "stress_key": (
                                        f"dataset::scene::{profile}::translation::"
                                        f"{'exact' if residual == 0.0 else 'r1of1024'}"
                                    ),
                                    "epsilon_255": epsilon255,
                                },
                            }
                        )
                        rows.append(
                            {
                                "case_id": case_id,
                                "scene_id": "dataset::scene",
                                "dataset_id": "dataset",
                                "source_scene_id": "scene",
                                "representation": "test",
                                "edit_family": "translation",
                                "coupling_regime": "low",
                                "fallback_full": fallback,
                                "planner_work": 100.0 if fallback else 20.0,
                                "full_work": 100.0,
                                "qois": {
                                    "rgb_linf": {
                                        "epsilon": epsilon255 / 255.0,
                                        "certified_bound": 0.0,
                                        "measured_full_reference_error": 0.0,
                                    }
                                },
                                "candidateDiagnostics": {
                                    "candidateRgbBound": (
                                        2.0 / 255.0 if fallback else 0.0
                                    ),
                                    "candidateActualRgbError": (
                                        0.5 / 255.0 if fallback else 0.0
                                    ),
                                    "sourceEditRgbBound": 4.0 / 255.0,
                                    "sourceEditActualRgbError": 2.0 / 255.0,
                                    "postRepairResidualBound": (
                                        1.0 / 255.0 if fallback else 0.0
                                    ),
                                    "productionResolvedRgbBound": (
                                        1.0 / 255.0 if fallback else 0.0
                                    ),
                                    "candidateWork": (
                                        25.0 if fallback else 20.0
                                    ),
                                    "affectedPixelFraction": 0.05,
                                    "repairMode": (
                                        "certified-graded-residual-v1"
                                        if fallback
                                        else "exact-changed-support-v1"
                                    ),
                                    "repairResidualScaleRequested": residual,
                                    "repairOmittedGaussians": 0,
                                    "repairAppliedChangedGaussians": 10,
                                    "repairCertificateViolationPixels": 0,
                                },
                            }
                        )
                        manifest_dir = campaign_dir / "cases" / case_id
                        manifest_dir.mkdir(parents=True)
                        (manifest_dir / "replay-manifest.json").write_text(
                            json.dumps(
                                {
                                    "production_certificate": {
                                        "temporalFullFrameFallback": fallback,
                                        "outputConePlanner": {
                                            "fullRepair": fallback,
                                            "temporalRepairSelected": fallback,
                                            "resolvedRgbBound": (
                                                1.0 / 255.0 if fallback else 0.0
                                            ),
                                            "historyWeight": 0.9,
                                            "temporalRepairWork": (
                                                100.0 if fallback else 10.0
                                            ),
                                            "plannerWork": (
                                                100.0 if fallback else 20.0
                                            ),
                                            "fullWork": 100.0,
                                        },
                                    }
                                }
                            )
                        )

            campaign = {
                "campaignId": "test-v4",
                "protocol": "post-reviewer-locality-v4",
                "cases": cases,
            }
            report = postmortem.build(rows, campaign, campaign_dir)

        self.assertTrue(report["exactRepairAllLocal"])
        self.assertTrue(report["nonzeroResidualAllFull"])
        self.assertEqual(
            report["profileDecisionSensitivity"]["decisionSensitiveGroups"],
            0,
        )
        self.assertEqual(
            report["epsilonDecisionSensitivity"]["decisionSensitiveGroups"],
            0,
        )
        self.assertEqual(
            report["residualDecisionSensitivity"]["decisionSensitiveGroups"],
            4,
        )
        self.assertEqual(
            report["fallbackCauseCounts"],
            {"production-full-full-frame-temporal-support": 4},
        )


if __name__ == "__main__":
    unittest.main()
