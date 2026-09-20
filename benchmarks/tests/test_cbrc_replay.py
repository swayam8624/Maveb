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

    def test_certificate_violation_is_fatal(self):
        with self.assertRaisesRegex(RuntimeError, "FATAL CBRC certificate violation"):
            mod.finalize_row(
                manifest(),
                oracle(bound=0.03, actual=0.04, certified=False),
                4,
            )


if __name__ == "__main__":
    unittest.main()
