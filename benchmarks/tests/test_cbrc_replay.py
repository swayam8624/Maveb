from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/cbrc_replay.py"
spec = importlib.util.spec_from_file_location("cbrc_replay", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def manifest():
    return {
        "scene_id": "fixture",
        "revision_id": "move-1",
        "git_sha": "abc",
        "graph_version": "g1",
        "bound_version": "b1",
        "edit_class": "gaussian",
        "coupling_regime": "low",
        "hard_closure_nodes": 1,
        "candidate_cone_nodes": 3,
        "total_nodes": 10,
        "candidate_work": 3.0,
        "full_work": 10.0,
    }


def oracle(bound=0.05, actual=0.04, within=True, certified=True):
    return {
        "changedFraction": 0.1,
        "affectedPixelFraction": 0.2,
        "effectivity": bound / max(actual, 1e-15),
        "certificateViolationPixels": 0 if certified else 1,
        "certified": certified,
        "withinTolerance": within,
        "qois": {
            "rgb_linf": {
                "epsilon": 0.06,
                "certified_bound": bound,
                "measured_full_reference_error": actual,
            }
        },
    }


class CBRCReplayTests(unittest.TestCase):
    def test_local_candidate_is_kept_when_certified_and_within_tolerance(self):
        row = mod.finalize_row(manifest(), oracle(), 0)
        self.assertFalse(row["fallback_full"])
        self.assertEqual(row["repair_cone_nodes"], 3)
        self.assertEqual(row["planner_work"], 3.0)

    def test_code_three_becomes_full_rebuild_not_dropped_trial(self):
        row = mod.finalize_row(manifest(), oracle(bound=0.08, within=False), 3)
        self.assertTrue(row["fallback_full"])
        self.assertEqual(row["repair_cone_nodes"], 10)
        self.assertEqual(row["planner_work"], 10.0)
        self.assertEqual(row["qois"]["rgb_linf"]["certified_bound"], 0.0)
        self.assertEqual(
            row["candidateDiagnostics"]["candidateRgbBound"], 0.08
        )

    def test_auto_diff_manifest_uses_detect_flag(self):
        m = manifest()
        m.update(
            {
                "before_ply": "before.ply",
                "after_ply": "after.ply",
                "epsilon_rgb_linf": 0.1,
                "detect_changed": True,
                "camera": {
                    "width": 64,
                    "height": 64,
                    "focal_x": 70,
                    "focal_y": 70,
                    "center_x": 32,
                    "center_y": 32,
                },
            }
        )
        m.pop("changed_indices", None)
        command = mod.build_oracle_command(Path("oracle"), m)
        self.assertIn("--detect-changed", command)
        self.assertNotIn("--changed", command)

    def test_reviewer_partial_repair_manifest_threads_oracle_flag(self):
        m = manifest()
        m.update(
            {
                "before_ply": "before.ply",
                "after_ply": "after.ply",
                "epsilon_rgb_linf": 0.1,
                "changed_indices": [1, 2, 3],
                "repair_omit_fraction": 0.05,
                "camera": {
                    "width": 64,
                    "height": 64,
                    "focal_x": 70,
                    "focal_y": 70,
                    "center_x": 32,
                    "center_y": 32,
                },
            }
        )
        command = mod.build_oracle_command(Path("oracle"), m)
        self.assertIn("--repair-omit-fraction", command)
        index = command.index("--repair-omit-fraction")
        self.assertEqual(command[index + 1], "0.05")

    def test_production_partial_repair_keeps_nonzero_certified_residual(self):
        m = manifest()
        m["production_certificate"] = {
            "maximumCurrentRgbBound": 0.5,
            "invalidationCoversCertifiedSupport": True,
            "outputConePlanner": {
                "stable": True,
                "passes": True,
                "fullRepair": False,
                "temporalRepairSelected": True,
                "resolvedRgbBound": 0.001,
            },
        }
        source = oracle(bound=0.5, actual=0.2, within=False)
        source["repair_qois"] = {
            "rgb_linf": {
                "epsilon": 0.06,
                "certified_bound": 0.02,
                "measured_full_reference_error": 0.012,
            }
        }
        source.update(
            {
                "repairMode": "certified-omitted-gaussians-v1",
                "repairOmitFractionRequested": 0.05,
                "repairOmittedGaussians": 4,
                "repairAppliedChangedGaussians": 96,
                "repairCertificateViolationPixels": 0,
            }
        )
        row = mod.finalize_row(m, source, 3)
        self.assertFalse(row["fallback_full"])
        self.assertAlmostEqual(
            row["qois"]["rgb_linf"]["measured_full_reference_error"],
            0.012,
        )
        self.assertAlmostEqual(
            row["qois"]["rgb_linf"]["certified_bound"],
            0.021,
        )
        self.assertEqual(
            row["candidateDiagnostics"]["repairMode"],
            "certified-omitted-gaussians-v1",
        )
        self.assertEqual(
            row["candidateDiagnostics"]["repairOmittedGaussians"],
            4,
        )

    def test_native_scalar_work_supports_uncalibrated_real_campaign(self):
        m = manifest()
        m.pop("candidate_work")
        m.pop("full_work")
        m["native_scalar_work"] = {
            "candidate": 64,
            "full": 1024,
            "unit": "temporal-pixels",
            "model_version": "temporal-pixel-work-v1",
        }
        row = mod.finalize_row(m, oracle(), 0)
        self.assertEqual(row["planner_work"], 64)
        self.assertEqual(row["full_work"], 1024)
        self.assertEqual(row["work_cost_model_version"], "temporal-pixel-work-v1")
        self.assertEqual(row["work_cost_unit"], "temporal-pixels")

    def test_frozen_work_model_converts_native_ledger(self):
        m = manifest()
        m.pop("candidate_work")
        m.pop("full_work")
        m["work_ledger"] = {
            "domains": {
                "gaussiansUpdated": {
                    "incremental": 10,
                    "full": 100,
                    "unit": "gaussians",
                },
                "gpuPublicationBytes": {
                    "incremental": 1000,
                    "full": 10000,
                    "unit": "bytes",
                },
            }
        }
        m["work_cost_model"] = {
            "version": "fixture-cost-v1",
            "cost_unit": "ms",
            "domains": {
                "gaussiansUpdated": {
                    "unit": "gaussians",
                    "cost_per_unit": 0.01,
                },
                "gpuPublicationBytes": {
                    "unit": "bytes",
                    "cost_per_unit": 1e-6,
                },
            },
        }
        row = mod.finalize_row(m, oracle(), 0)
        self.assertAlmostEqual(row["planner_work"], 0.101)
        self.assertAlmostEqual(row["full_work"], 1.01)
        self.assertEqual(row["work_cost_model_version"], "fixture-cost-v1")
        self.assertEqual(row["work_cost_unit"], "ms")


    def test_production_local_repair_uses_post_repair_residual_not_edit_magnitude(self):
        m = manifest()
        m["production_certificate"] = {
            "maximumCurrentRgbBound": 0.5,
            "invalidationCoversCertifiedSupport": True,
            "outputConePlanner": {
                "stable": True,
                "passes": True,
                "fullRepair": False,
                "temporalRepairSelected": True,
                "resolvedRgbBound": 0.0,
            },
        }
        source = oracle(bound=0.5, actual=0.2, within=False)
        source["repair_qois"] = {
            "rgb_linf": {
                "epsilon": 0.06,
                "certified_bound": 2e-6,
                "measured_full_reference_error": 0.0,
            }
        }
        row = mod.finalize_row(m, source, 3)
        self.assertFalse(row["fallback_full"])
        self.assertEqual(row["planner_work"], 3.0)
        self.assertAlmostEqual(row["qois"]["rgb_linf"]["certified_bound"], 2e-6)
        self.assertEqual(
            row["candidateDiagnostics"]["sourceEditActualRgbError"],
            0.2,
        )
        self.assertTrue(
            row["candidateDiagnostics"]["sourceEffectOnlyOracleReturnCode"]
        )

    def test_production_full_repair_remains_full_fallback(self):
        m = manifest()
        m["production_certificate"] = {
            "maximumCurrentRgbBound": 0.5,
            "invalidationCoversCertifiedSupport": True,
            "outputConePlanner": {
                "stable": True,
                "passes": True,
                "fullRepair": True,
                "temporalRepairSelected": False,
                "resolvedRgbBound": 0.0,
            },
        }
        source = oracle(bound=0.5, actual=0.2, within=False)
        source["repair_qois"] = {
            "rgb_linf": {
                "epsilon": 0.06,
                "certified_bound": 2e-6,
                "measured_full_reference_error": 0.0,
            }
        }
        row = mod.finalize_row(m, source, 3)
        self.assertTrue(row["fallback_full"])
        self.assertEqual(row["planner_work"], 10.0)
        self.assertEqual(row["qois"]["rgb_linf"]["certified_bound"], 0.0)

    def test_production_offline_bound_disagreement_is_fatal(self):
        m = manifest()
        m["production_certificate"] = {
            "maximumCurrentRgbBound": 0.07,
        }
        with self.assertRaisesRegex(RuntimeError, "bound disagreement"):
            mod.finalize_row(m, oracle(bound=0.05), 0)

    def test_vertical_slice_scope_is_preserved(self):
        m = manifest()
        m["execution_mode"] = "certified-supplied-cone"
        m["graph_scope"] = "gaussian-vertical-slice-v1"
        row = mod.finalize_row(m, oracle(), 0)
        self.assertEqual(row["execution_mode"], "certified-supplied-cone")
        self.assertEqual(row["graph_scope"], "gaussian-vertical-slice-v1")

    def test_certificate_violation_is_fatal(self):
        with self.assertRaisesRegex(RuntimeError, "FATAL CBRC certificate violation"):
            mod.finalize_row(
                manifest(),
                oracle(bound=0.03, actual=0.04, certified=False),
                4,
            )


if __name__ == "__main__":
    unittest.main()
