from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/cbrc_campaign.py"
spec = importlib.util.spec_from_file_location("cbrc_campaign", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def row(*, fallback=False, coupling="low", actual=0.02, bound=0.03):
    return {
        "scene_id": "scene",
        "revision_id": "r",
        "coupling_regime": coupling,
        "fallback_full": fallback,
        "qois": {
            "rgb_linf": {
                "epsilon": 0.04,
                "certified_bound": 0.0 if fallback else bound,
                "measured_full_reference_error": 0.0 if fallback else actual,
            }
        },
    }


class CBRCCampaignTests(unittest.TestCase):
    def test_complete_campaign_gate_passes(self):
        rows = [
            row(),
            row(),
            row(),
            row(coupling="high"),
            row(fallback=True, coupling="adversarial"),
        ]
        result = mod.gate_rows(
            rows,
            {
                "minimum_revisions": 5,
                "minimum_scenes": 1,
                "require_local_success": True,
                "require_full_fallback": True,
                "require_high_coupling": True,
            },
        )
        self.assertTrue(result["pass"])

    def test_missing_fallback_fails(self):
        result = mod.gate_rows(
            [row() for _ in range(5)],
            {
                "minimum_revisions": 5,
                "minimum_scenes": 1,
                "require_local_success": True,
                "require_full_fallback": True,
                "require_high_coupling": False,
            },
        )
        self.assertFalse(result["pass"])
        self.assertFalse(result["gates"]["hasAutomaticFullFallback"])

    def test_capture_case_requires_three_value_target(self):
        case = {
            "id": "bad",
            "epsilon": 0.1,
            "revision": {
                "archive": "world",
                "entity": 1,
                "target": [1, 2],
                "timestamp": 2,
            },
        }
        with self.assertRaisesRegex(ValueError, "target"):
            mod.capture_case(
                case,
                revision_tool=Path("tool"),
                case_dir=Path("out"),
            )

    def test_native_python_planner_parity(self):
        manifest = {
            "production_certificate": {
                "outputConePlanner": {
                    "plannerWork": 25.0,
                    "passes": True,
                    "fullRepair": False,
                }
            }
        }
        baseline = {
            "baselines": {
                "CBRC": {
                    "work": 25.0,
                    "passes": True,
                    "usedFullRebuild": False,
                }
            }
        }
        result = mod.verify_native_python_planner_parity(manifest, baseline)
        self.assertTrue(result["pass"])
        self.assertEqual(result["workDelta"], 0.0)

    def test_native_python_planner_parity_detects_fallback_mismatch(self):
        manifest = {
            "production_certificate": {
                "outputConePlanner": {
                    "plannerWork": 100.0,
                    "passes": True,
                    "fullRepair": True,
                }
            }
        }
        baseline = {
            "baselines": {
                "CBRC": {
                    "work": 100.0,
                    "passes": True,
                    "usedFullRebuild": False,
                }
            }
        }
        result = mod.verify_native_python_planner_parity(manifest, baseline)
        self.assertFalse(result["pass"])
        self.assertFalse(result["fallbackMatch"])

    def test_baseline_summary_aggregates_method_statistics(self):
        records = [
            {
                "baselines": {
                    "CBRC": {
                        "passes": True,
                        "usedFullRebuild": False,
                        "workRatioFull": 0.25,
                    }
                },
                "ablations": {
                    "ABLATE_NO_FALLBACK": {
                        "passes": False,
                        "usedFullRebuild": False,
                        "workRatioFull": 0.1,
                    }
                },
            },
            {
                "baselines": {
                    "CBRC": {
                        "passes": True,
                        "usedFullRebuild": True,
                        "workRatioFull": 1.0,
                    }
                },
                "ablations": {
                    "ABLATE_NO_FALLBACK": {
                        "passes": True,
                        "usedFullRebuild": False,
                        "workRatioFull": 0.2,
                    }
                },
            },
        ]
        summary = mod.baseline_summary(records)
        self.assertEqual(summary["baselines"]["CBRC"]["passRate"], 1.0)
        self.assertEqual(
            summary["baselines"]["CBRC"]["fullRebuildRate"], 0.5
        )
        self.assertEqual(
            summary["baselines"]["CBRC"]["medianWorkRatioFull"], 0.625
        )
        self.assertEqual(
            summary["ablations"]["ABLATE_NO_FALLBACK"]["passRate"], 0.5
        )

    def test_certificate_violation_fails(self):
        rows = [row() for _ in range(4)] + [row(actual=0.04, bound=0.03)]
        result = mod.gate_rows(
            rows,
            {
                "minimum_revisions": 5,
                "minimum_scenes": 1,
                "require_local_success": True,
                "require_full_fallback": False,
                "require_high_coupling": False,
            },
        )
        self.assertFalse(result["pass"])
        self.assertFalse(result["gates"]["noCertificateViolations"])


if __name__ == "__main__":
    unittest.main()
