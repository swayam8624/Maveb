from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "cbrc_freeze_reviewer_budgeted_v3.py"
)
spec = importlib.util.spec_from_file_location("cbrc_freeze_reviewer_budgeted_v3", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class ReviewerV3FreezeTests(unittest.TestCase):
    def test_converts_fixed_fraction_probe_to_budgeted_protocol(self):
        campaign = {
            "campaignId": "old",
            "protocol": "old",
            "severityProfiles": [
                {"name": "medium", "repair_omit_fraction": 0.01},
                {"name": "strong", "repair_omit_fraction": 0.05},
            ],
            "cases": [
                {
                    "id": "case",
                    "reviewer_repair_omit_fraction": 0.01,
                    "matrix_tags": {
                        "protocol": "old",
                        "repair_omit_fraction": 0.01,
                    },
                }
            ],
        }
        provenance = {
            "artifact": "old",
            "generator": "old",
            "severityProfiles": [
                {"name": "medium", "repair_omit_fraction": 0.01}
            ],
            "frozen_inputs": [
                {
                    "case_id": "case",
                    "repair_omit_fraction": 0.01,
                    "matrix": {
                        "protocol": "old",
                        "repair_omit_fraction": 0.01,
                    },
                }
            ],
        }

        converted, converted_provenance = mod.convert_v2_to_v3(
            campaign,
            provenance,
            residual_budget_fraction=0.5,
        )

        self.assertEqual(converted["protocol"], mod.PROTOCOL)
        self.assertEqual(converted["campaignId"], mod.CAMPAIGN_ID)
        self.assertEqual(converted["repairResidualBudgetFraction"], 0.5)
        case = converted["cases"][0]
        self.assertNotIn("reviewer_repair_omit_fraction", case)
        self.assertEqual(case["reviewer_repair_residual_budget_fraction"], 0.5)
        self.assertNotIn("repair_omit_fraction", case["matrix_tags"])
        self.assertEqual(
            case["matrix_tags"]["repair_residual_budget_fraction"], 0.5
        )
        self.assertEqual(case["matrix_tags"]["protocol"], mod.PROTOCOL)

        frozen = converted_provenance["frozen_inputs"][0]
        self.assertNotIn("repair_omit_fraction", frozen)
        self.assertEqual(frozen["repair_residual_budget_fraction"], 0.5)
        self.assertEqual(converted_provenance["protocol"], mod.PROTOCOL)

    def test_rejects_degenerate_budget_fraction(self):
        with self.assertRaises(ValueError):
            mod.convert_v2_to_v3({}, {}, residual_budget_fraction=0.0)
        with self.assertRaises(ValueError):
            mod.convert_v2_to_v3({}, {}, residual_budget_fraction=1.0)


if __name__ == "__main__":
    unittest.main()
