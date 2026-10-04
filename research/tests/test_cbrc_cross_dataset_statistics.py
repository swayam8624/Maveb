from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[2] / "research/analysis/cbrc_cross_dataset_statistics.py"
SPEC = importlib.util.spec_from_file_location("cbrc_cross_dataset_statistics", MODULE_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(mod)


def row(dataset: str, work: float, full: float = 100.0, *, fallback: bool = False, violation: bool = False):
    bound = 0.02
    actual = 0.03 if violation else 0.01
    return {
        "dataset_id": dataset,
        "source_scene_id": f"{dataset}-scene",
        "representation": f"{dataset}-repr",
        "edit_family": "translation",
        "coupling_regime": "high" if fallback else "low",
        "planner_work": work,
        "full_work": full,
        "fallback_full": fallback,
        "qois": {
            "rgb_linf": {
                "epsilon": 0.04,
                "certified_bound": bound,
                "measured_full_reference_error": actual,
            }
        },
    }


class CrossDatasetStatisticsTests(unittest.TestCase):
    def test_group_summary_reports_work_and_contract(self):
        values = [row("a", 20.0), row("a", 40.0), row("a", 100.0, fallback=True)]
        summary = mod.summarize_group(values, iterations=200, seed=1)
        self.assertEqual(summary["cases"], 3)
        self.assertEqual(summary["localCases"], 2)
        self.assertEqual(summary["fullFallbackCases"], 1)
        self.assertEqual(summary["certificateViolations"], 0)
        self.assertAlmostEqual(summary["workRatioFull"]["median"], 0.4)

    def test_contract_violation_is_detected(self):
        self.assertTrue(mod.contract_violation(row("a", 20.0, violation=True)))
        self.assertFalse(mod.contract_violation(row("a", 20.0)))

    def test_exact_sign_test(self):
        self.assertEqual(mod.exact_sign_test(0, 0), None)
        self.assertAlmostEqual(mod.exact_sign_test(5, 0), 0.0625)

    def test_baseline_pairing_uses_only_both_certified(self):
        records = [
            {
                "baselines": {
                    "CBRC": {"passes": True, "workRatioFull": 0.3},
                    "EXACT": {"passes": True, "workRatioFull": 0.7},
                },
                "ablations": {},
            },
            {
                "baselines": {
                    "CBRC": {"passes": True, "workRatioFull": 0.4},
                    "EXACT": {"passes": False, "workRatioFull": 0.2},
                },
                "ablations": {},
            },
        ]
        result = mod.baseline_stats(records)["baselines"]["EXACT"]
        self.assertEqual(result["bothCertifiedCases"], 1)
        self.assertEqual(result["cbrcLowerWorkCasesAmongBothCertified"], 1)
        self.assertAlmostEqual(result["medianOtherMinusCbrcWorkRatio"], 0.4)


if __name__ == "__main__":
    unittest.main()
