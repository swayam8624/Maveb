from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "analysis/cbrc_paper_artifacts.py"
spec = importlib.util.spec_from_file_location("cbrc_paper_artifacts", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def row(fallback=False, coupling="low"):
    return {
        "scene_id": "scene",
        "revision_id": "rev",
        "changed_fraction": 0.1,
        "coupling_regime": coupling,
        "repair_cone_nodes": 2,
        "total_nodes": 10,
        "fallback_full": fallback,
        "planner_work": 2.0 if not fallback else 10.0,
        "full_work": 10.0,
        "qois": {
            "rgb_linf": {
                "epsilon": 0.1,
                "certified_bound": 0.08 if not fallback else 0.0,
                "measured_full_reference_error": 0.05 if not fallback else 0.0,
            }
        },
        "work_ledger": {
            "domains": {
                "gaussiansUpdated": {
                    "incremental": 2,
                    "full": 10,
                    "unit": "gaussians",
                }
            }
        },
        "candidateDiagnostics": {"candidateRgbBound": 0.08},
    }


class CBRCPaperArtifactsTests(unittest.TestCase):
    def test_summary_detects_no_violation(self):
        result = mod.summarize([row(), row(True, "high")])
        self.assertEqual(result["certificateViolations"], 0)
        self.assertEqual(result["fallbackRate"], 0.5)

    def test_all_nonspatial_figures_emit(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            rows = [row(), row(True, "high")]
            mod.f1(rows, output)
            mod.f2(rows, output)
            mod.f3(rows, output)
            mod.f4(rows, output)
            mod.f5(rows, output)
            mod.f6(rows, output)
            mod.f8(rows, output)
            for number in (1, 2, 3, 4, 5, 6, 8):
                self.assertTrue(any(output.glob(f"F{number}_*.svg")))

    def test_method_comparison_tables_emit(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            records = [
                {
                    "case_id": "a",
                    "scene_id": "scene",
                    "coupling_regime": "low",
                    "baselines": {
                        "CBRC": {
                            "passes": True,
                            "usedFullRebuild": False,
                            "workRatioFull": 0.25,
                            "work": 25.0,
                            "fullWork": 100.0,
                        }
                    },
                    "ablations": {
                        "ABLATE_NO_FALLBACK": {
                            "passes": False,
                            "usedFullRebuild": False,
                            "workRatioFull": 0.1,
                            "work": 10.0,
                            "fullWork": 100.0,
                        }
                    },
                },
                {
                    "case_id": "b",
                    "scene_id": "scene",
                    "coupling_regime": "high",
                    "baselines": {
                        "CBRC": {
                            "passes": True,
                            "usedFullRebuild": True,
                            "workRatioFull": 1.0,
                            "work": 100.0,
                            "fullWork": 100.0,
                        }
                    },
                    "ablations": {
                        "ABLATE_NO_FALLBACK": {
                            "passes": True,
                            "usedFullRebuild": False,
                            "workRatioFull": 0.2,
                            "work": 20.0,
                            "fullWork": 100.0,
                        }
                    },
                },
            ]
            summary = mod.method_comparison_tables(records, output)
            self.assertEqual(summary["baselines"]["CBRC"]["pass_rate"], 1.0)
            self.assertEqual(
                summary["baselines"]["CBRC"]["full_rebuild_rate"], 0.5
            )
            self.assertEqual(
                summary["baselines"]["CBRC"]["median_work_ratio_full"], 0.625
            )
            self.assertTrue((output / "T1_method_case_results.csv").exists())
            self.assertTrue((output / "T2_method_summary.csv").exists())

    def test_spatial_figure_emits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spatial = root / "spatial.csv"
            spatial.write_text(
                "x,y,actual_rgb_linf,certified_bound,certificate_violation\n"
                "0,0,0.01,0.02,0\n1,0,0.00,0.01,0\n"
            )
            mod.f7(spatial, root, row())
            self.assertTrue((root / "F7_cone_support_residual.svg").exists())


if __name__ == "__main__":
    unittest.main()
