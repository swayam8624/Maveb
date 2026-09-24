from __future__ import annotations

import importlib.util
import subprocess
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


freeze = load_module(
    "cbrc_freeze_reviewer_locality_v4",
    "benchmarks/scripts/cbrc_freeze_reviewer_locality_v4.py",
)
trace = load_module(
    "cbrc_trace_case",
    "research/analysis/cbrc_trace_case.py",
)


class ReviewerLocalityV4ProtocolTests(unittest.TestCase):
    def test_protocol_is_small_frozen_locality_matrix(self):
        self.assertEqual(freeze.EPSILON_LEVELS_255, (1.0, 4.0, 16.0, 32.0))
        self.assertEqual(freeze.RESIDUAL_SCALES, (0.0, 1.0 / 1024.0))
        names = [profile["name"] for profile in freeze.SEVERITY_PROFILES]
        self.assertEqual(
            names,
            ["smallest-entity", "tiny-local", "local", "broad-control"],
        )
        fractions = [float(profile["entity_fraction"]) for profile in freeze.SEVERITY_PROFILES]
        self.assertEqual(fractions, sorted(fractions))
        self.assertLess(fractions[0], 0.001)
        self.assertGreaterEqual(fractions[-1], 0.10)

    def test_runner_shell_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(ROOT / "run_reviewer_locality_v4.sh")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class CaseTraceTests(unittest.TestCase):
    def test_trace_exposes_bound_sum_and_production_full_cause(self):
        row = {
            "case_id": "case-a",
            "dataset_id": "3rscan",
            "source_scene_id": "scene",
            "edit_family": "translation",
            "coupling_regime": "low",
            "fallback_full": True,
            "changed_fraction": 0.02,
            "hard_closure_nodes": 2,
            "total_nodes": 100,
            "planner_work": 100.0,
            "full_work": 100.0,
            "qois": {
                "rgb_linf": {
                    "epsilon": 4.0 / 255.0,
                    "certified_bound": 0.0,
                    "measured_full_reference_error": 0.0,
                }
            },
            "candidateDiagnostics": {
                "candidateConeNodes": 20,
                "candidateWork": 25.0,
                "candidateRgbBound": 3.0 / 255.0,
                "candidateActualRgbError": 2.0 / 255.0,
                "sourceEditRgbBound": 6.0 / 255.0,
                "sourceEditActualRgbError": 4.0 / 255.0,
                "postRepairResidualBound": 1.0 / 255.0,
                "postRepairActualRgbError": 0.5 / 255.0,
                "productionResolvedRgbBound": 2.0 / 255.0,
                "affectedPixelFraction": 0.1,
                "repairMode": "certified-graded-residual-v1",
                "repairResidualScaleRequested": 1.0 / 1024.0,
                "repairOmittedGaussians": 0,
                "repairAppliedChangedGaussians": 20,
                "repairCertificateViolationPixels": 0,
            },
        }
        manifest = {
            "production_certificate": {
                "invalidationCoversCertifiedSupport": True,
                "temporalFullFrameFallback": True,
                "outputConePlanner": {
                    "stable": True,
                    "passes": False,
                    "fullRepair": True,
                    "temporalRepairSelected": True,
                    "temporalValidationStable": True,
                    "resolvedRgbBound": 2.0 / 255.0,
                    "historyWeight": 0.9,
                    "temporalRepairWork": 100.0,
                    "plannerWork": 100.0,
                    "fullWork": 100.0,
                },
                "temporal": {"fullFrame": True, "pixelRatio": 1.0},
                "publication": {"byteRatio": 0.02},
            }
        }
        report = trace.trace_case(row, manifest)
        self.assertEqual(
            report["primaryCause"],
            "production-full-full-frame-temporal-support",
        )
        self.assertTrue(report["boundDecomposition"]["matchesCandidateBound"])
        self.assertEqual(
            report["boundDecomposition"]["dominantTerm"],
            "productionResolvedRgbBound",
        )
        self.assertLess(report["candidate"]["bound"], report["epsilon"])
        self.assertEqual(report["decision"], "FULL")


if __name__ == "__main__":
    unittest.main()
