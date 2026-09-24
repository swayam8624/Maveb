from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "analysis"
    / "cbrc_reviewer_evidence.py"
)
spec = importlib.util.spec_from_file_location("cbrc_reviewer_evidence", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class ReviewerEvidenceBudgetedModeTests(unittest.TestCase):
    def test_budgeted_partial_repair_counts_as_certified_partial_mode(self):
        campaign = {
            "protocol": "post-reviewer-budgeted-partial-repair-v3",
            "cases": [
                {
                    "id": "case",
                    "dataset_id": "3rscan",
                    "source_scene_id": "scene",
                    "edit_family": "translation",
                    "coupling_regime": "medium",
                    "matrix_tags": {
                        "stress_key": "3rscan::scene::medium::translation",
                        "dataset_id": "3rscan",
                        "source_scene_id": "scene",
                        "edit_family": "translation",
                        "severity_profile": "medium",
                        "epsilon_255": 8.0,
                    },
                }
            ],
        }
        rows = [
            {
                "case_id": "case",
                "scene_id": "3rscan::scene",
                "dataset_id": "3rscan",
                "source_scene_id": "scene",
                "edit_family": "translation",
                "coupling_regime": "medium",
                "fallback_full": False,
                "planner_work": 10.0,
                "full_work": 100.0,
                "qois": {
                    "rgb_linf": {
                        "epsilon": 8.0 / 255.0,
                        "certified_bound": 0.01,
                        "measured_full_reference_error": 0.001,
                    }
                },
                "candidateDiagnostics": {
                    "candidateRgbBound": 0.01,
                    "candidateActualRgbError": 0.001,
                    "affectedPixelFraction": 0.1,
                    "repairMode": "certified-budgeted-omitted-gaussians-v2",
                    "repairOmitFractionRequested": 0.0,
                    "repairResidualBudgetFraction": 0.5,
                    "repairResidualRemainingSlack": 0.02,
                    "repairResidualBudgetRequested": 0.01,
                    "repairResidualBudget": 0.009998,
                    "repairOmittedGaussians": 2,
                    "repairAppliedChangedGaussians": 18,
                    "repairCertificateViolationPixels": 0,
                },
            }
        ]

        report, records = mod.analyze(rows, campaign)

        self.assertEqual(len(records), 1)
        self.assertEqual(report["certifiedPartialRepairCases"], 1)
        self.assertTrue(report["readinessGates"]["hasCertifiedPartialRepairMode"])
        self.assertEqual(records[0]["repairResidualBudgetFraction"], 0.5)


if __name__ == "__main__":
    unittest.main()
