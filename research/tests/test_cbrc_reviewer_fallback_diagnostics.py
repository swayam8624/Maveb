from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "analysis"
    / "cbrc_reviewer_fallback_diagnostics.py"
)
spec = importlib.util.spec_from_file_location("cbrc_reviewer_fallback_diagnostics", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def row(
    *,
    fallback: bool,
    epsilon: float = 0.02,
    candidate_bound: float = 0.01,
    candidate_actual: float = 0.005,
    candidate_work: float = 20.0,
    full_work: float = 100.0,
):
    return {
        "case_id": "case",
        "dataset_id": "dataset",
        "edit_family": "translation",
        "fallback_full": fallback,
        "full_work": full_work,
        "qois": {
            "rgb_linf": {
                "epsilon": epsilon,
                "certified_bound": 0.0 if fallback else candidate_bound,
                "measured_full_reference_error": 0.0 if fallback else candidate_actual,
            }
        },
        "candidateDiagnostics": {
            "candidateRgbBound": candidate_bound,
            "candidateActualRgbError": candidate_actual,
            "candidateWork": candidate_work,
            "sourceEditRgbBound": 0.04,
            "postRepairResidualBound": 0.002,
            "productionResolvedRgbBound": 0.008,
        },
    }


def manifest(
    *,
    full_repair: bool,
    temporal_full_frame: bool,
    temporal_work: float,
    full_work: float = 100.0,
):
    return {
        "production_certificate": {
            "temporalFullFrameFallback": temporal_full_frame,
            "outputConePlanner": {
                "fullRepair": full_repair,
                "temporalRepairSelected": True,
                "historyWeight": 0.9,
                "temporalRepairWork": temporal_work,
                "fullWork": full_work,
                "resolvedRgbBound": 0.0 if full_repair else 0.008,
            },
        }
    }


class ReviewerFallbackDiagnosticTests(unittest.TestCase):
    def test_identifies_production_full_from_full_frame_temporal_support(self):
        result = mod.classify_row(
            row(
                fallback=True,
                candidate_work=100.0,
                full_work=100.0,
            ),
            manifest=manifest(
                full_repair=True,
                temporal_full_frame=True,
                temporal_work=100.0,
            ),
        )
        self.assertEqual(
            result["cause"],
            "production-full-full-frame-temporal-support",
        )
        self.assertEqual(result["temporalRepairWorkRatioFull"], 1.0)
        self.assertTrue(result["productionFullRepair"])

    def test_identifies_post_repair_bound_failure(self):
        result = mod.classify_row(
            row(
                fallback=True,
                epsilon=0.02,
                candidate_bound=0.03,
                candidate_actual=0.01,
                candidate_work=20.0,
            ),
            manifest=manifest(
                full_repair=False,
                temporal_full_frame=False,
                temporal_work=20.0,
            ),
        )
        self.assertEqual(
            result["cause"],
            "post-repair-certified-bound-over-epsilon",
        )

    def test_local_case_is_not_reclassified(self):
        result = mod.classify_row(
            row(fallback=False),
            manifest=manifest(
                full_repair=False,
                temporal_full_frame=False,
                temporal_work=20.0,
            ),
        )
        self.assertEqual(result["cause"], "local-selected")

    def test_summary_keeps_diagnostic_read_only_and_explanation_counts(self):
        records = [
            mod.classify_row(
                row(fallback=True, candidate_work=100.0),
                manifest=manifest(
                    full_repair=True,
                    temporal_full_frame=True,
                    temporal_work=100.0,
                ),
            ),
            mod.classify_row(
                row(
                    fallback=True,
                    candidate_bound=0.03,
                    candidate_work=20.0,
                ),
                manifest=manifest(
                    full_repair=False,
                    temporal_full_frame=False,
                    temporal_work=20.0,
                ),
            ),
        ]
        result = mod.summarize(records)
        self.assertTrue(result["readOnlyDiagnostic"])
        self.assertTrue(result["allFallbacksExplained"])
        self.assertEqual(result["fallbackCases"], 2)
        self.assertEqual(result["productionFullRepairCases"], 1)


if __name__ == "__main__":
    unittest.main()
