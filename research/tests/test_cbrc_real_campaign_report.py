from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "analysis/cbrc_real_campaign_report.py"
spec = importlib.util.spec_from_file_location("cbrc_real_campaign_report", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class CBRCCampaignReportTests(unittest.TestCase):
    def test_zero_residual_effectivity_is_reported_as_undefined(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = {
                "scene_id": "scene",
                "revision_id": "rev",
                "fallback_full": False,
                "planner_work": 5.0,
                "full_work": 100.0,
                "work_cost_unit": "ms",
                "work_cost_model_version": "frozen-v1",
                "qois": {
                    "rgb_linf": {
                        "measured_full_reference_error": 0.0,
                        "certified_bound": 2e-6,
                        "epsilon": 1e-3,
                    }
                },
                "candidateDiagnostics": {
                    "candidateActualRgbError": 0.0,
                    "candidateRgbBound": 2e-6,
                    "sourceEditActualRgbError": 0.0,
                    "sourceEditRgbBound": 1.0,
                    "effectivity": 1e15,
                },
                "work_ledger": {
                    "domains": {
                        "gaussiansUpdated": {
                            "incremental": 5.0,
                            "full": 100.0,
                        }
                    }
                },
            }
            (root / "campaign-rows.jsonl").write_text(json.dumps(row) + "\n")
            (root / "campaign-gates.json").write_text(
                json.dumps({"pass": True, "certificateViolations": [], "gates": {}})
            )
            (root / "campaign-evaluation.json").write_text(json.dumps({"pass": True}))
            (root / "baseline-summary.json").write_text(json.dumps({}))

            result = mod.summarize(root)
            self.assertIsNone(result["medianSelectedEffectivity"])
            self.assertIsNone(result["medianSourceEditEffectivity"])
            self.assertEqual(result["zeroMeasuredSelectedErrorCount"], 1)
            self.assertEqual(result["zeroMeasuredSourceEditErrorCount"], 1)
            self.assertEqual(result["sourceEffectivityMismatchCount"], 0)
            self.assertEqual(result["maximumMeasuredSelectedError"], 0.0)


if __name__ == "__main__":
    unittest.main()
