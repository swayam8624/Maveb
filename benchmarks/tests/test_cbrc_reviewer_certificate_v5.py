from __future__ import annotations

import importlib.util
import json
import subprocess
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


freeze = load_module(
    "cbrc_freeze_reviewer_certificate_v5",
    "benchmarks/scripts/cbrc_freeze_reviewer_certificate_v5.py",
)
audit = load_module(
    "cbrc_v5_certificate_analysis",
    "research/analysis/cbrc_v5_certificate_analysis.py",
)


class ReviewerCertificateV5ProtocolTests(unittest.TestCase):
    def test_frozen_matrix_matches_declared_certificate_experiment(self):
        self.assertEqual(freeze.EDIT_FAMILIES, ("opacity", "translation"))
        self.assertEqual(
            freeze.EPSILON_LEVELS_255,
            (1.0, 2.0, 4.0, 8.0, 16.0, 32.0),
        )
        self.assertEqual(
            freeze.RESIDUAL_SCALES,
            (0.0, 1.0 / 4096.0, 1.0 / 1024.0, 1.0 / 256.0),
        )
        self.assertEqual(len(freeze.SEVERITY_PROFILES), 4)
        self.assertEqual(
            {float(profile["delta_fraction"]) for profile in freeze.SEVERITY_PROFILES},
            {0.06},
        )
        self.assertEqual(
            {float(profile["history_weight"]) for profile in freeze.SEVERITY_PROFILES},
            {0.90},
        )
        self.assertTrue(
            all(bool(profile["history_stable"]) for profile in freeze.SEVERITY_PROFILES)
        )

    def test_matrix_size_is_fixed_before_outcomes(self):
        datasets = 4
        expected = (
            datasets
            * len(freeze.SEVERITY_PROFILES)
            * len(freeze.EDIT_FAMILIES)
            * len(freeze.RESIDUAL_SCALES)
            * len(freeze.EPSILON_LEVELS_255)
        )
        self.assertEqual(expected, 768)

    def test_certificate_audit_separates_validity_from_outcome(self):
        cases = []
        rows = []
        specs = (
            ("opacity", 0.0, "exact-zero-v1", 0.0),
            ("opacity", 1.0 / 4096.0, "opacity-delta-lipschitz-v1", 0.001),
            ("opacity", 1.0 / 1024.0, "opacity-delta-lipschitz-v1", 0.004),
            ("translation", 1.0 / 1024.0, "opacity-envelope-union-v1", 0.2),
        )

        with tempfile.TemporaryDirectory() as temporary:
            campaign_dir = Path(temporary)
            for serial, (family, residual, mode, residual_bound) in enumerate(specs, 1):
                case_id = f"case-{serial}"
                cases.append(
                    {
                        "id": case_id,
                        "scene_id": "dataset::scene",
                        "dataset_id": "dataset",
                        "source_scene_id": "scene",
                        "representation": "test",
                        "edit_family": family,
                        "coupling_regime": "low",
                        "epsilon": 32.0 / 255.0,
                        "matrix_tags": {
                            "severity_profile": "tiny-local",
                            "stress_key": (
                                f"dataset::scene::tiny-local::{family}::"
                                f"{residual:.12g}"
                            ),
                            "epsilon_255": 32.0,
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
                        "edit_family": family,
                        "coupling_regime": "low",
                        "fallback_full": False,
                        "planner_work": 20.0,
                        "full_work": 100.0,
                        "qois": {
                            "rgb_linf": {
                                "epsilon": 32.0 / 255.0,
                                "certified_bound": 0.01,
                                "measured_full_reference_error": 0.005,
                            }
                        },
                        "candidateDiagnostics": {
                            "candidateRgbBound": 0.01 + residual_bound,
                            "candidateActualRgbError": 0.005,
                            "sourceEditRgbBound": 0.01,
                            "sourceEditActualRgbError": 0.005,
                            "productionResolvedRgbBound": 0.01,
                            "postRepairResidualBound": residual_bound,
                            "postRepairActualRgbError": residual_bound * 0.25,
                            "candidateWork": 20.0,
                            "affectedPixelFraction": 0.05,
                            "repairMode": (
                                "exact-changed-support-v1"
                                if residual == 0.0
                                else "certified-graded-residual-v1"
                            ),
                            "repairCertificateMode": mode,
                            "repairResidualScaleRequested": residual,
                            "repairOmittedGaussians": 0,
                            "repairAppliedChangedGaussians": 4,
                            "repairCertificateViolationPixels": 0,
                        },
                    }
                )
                manifest = campaign_dir / "cases" / case_id
                manifest.mkdir(parents=True)
                (manifest / "replay-manifest.json").write_text(
                    json.dumps(
                        {
                            "production_certificate": {
                                "outputConePlanner": {
                                    "fullRepair": False,
                                    "temporalRepairSelected": False,
                                    "resolvedRgbBound": 0.01,
                                    "plannerWork": 20.0,
                                    "fullWork": 100.0,
                                    "temporalRepairWork": 5.0,
                                },
                                "temporalFullFrameFallback": False,
                            }
                        }
                    ),
                    encoding="utf-8",
                )

            campaign = {
                "campaignId": "test-v5",
                "protocol": "post-reviewer-opacity-delta-v5",
                "cases": cases,
            }
            report = audit.build(rows, campaign, campaign_dir)

        self.assertTrue(report["certificateExperimentValid"])
        self.assertTrue(all(report["validityGates"].values()))
        self.assertFalse(report["modeRoutingErrors"])
        self.assertFalse(report["monotonicityViolations"])
        self.assertEqual(
            report["modeByEditFamily"]["opacity"]["opacity-delta-lipschitz-v1"],
            2,
        )
        self.assertEqual(
            report["modeByEditFamily"]["translation"]["opacity-envelope-union-v1"],
            1,
        )

    def test_runner_shell_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(ROOT / "run_reviewer_certificate_v5.sh")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
