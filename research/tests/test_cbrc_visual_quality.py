from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "research/analysis/cbrc_visual_quality.py"
spec = importlib.util.spec_from_file_location("cbrc_visual_quality", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def write_case(root: Path, case_id: str, before_color, full_color, selected_color):
    visual = root / "cases" / case_id / "visuals"
    visual.mkdir(parents=True)
    Image.new("RGB", (16, 10), before_color).save(visual / "before.ppm")
    Image.new("RGB", (16, 10), full_color).save(visual / "full-after.ppm")
    Image.new("RGB", (16, 10), selected_color).save(visual / "selected-repair.ppm")
    Image.new("RGB", (16, 10), (0, 0, 0)).save(visual / "post-repair-residual.ppm")


class VisualQualityTests(unittest.TestCase):
    def test_exact_selected_render_and_visible_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            campaign = Path(directory) / "campaign"
            write_case(
                campaign,
                "case-a",
                (10, 20, 30),
                (40, 50, 60),
                (40, 50, 60),
            )
            rows = [
                {
                    "case_id": "case-a",
                    "scene_id": "scene-a",
                    "fallback_full": False,
                    "coupling_regime": "low",
                    "planner_work": 20.0,
                    "full_work": 100.0,
                }
            ]
            (campaign / "campaign-rows.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows)
            )
            report, records = mod.evaluate(campaign, rows, {"scene-a": "Dataset / Scene"})
            self.assertEqual(report["selectedExactCases"], 1)
            self.assertEqual(report["maximumSelectedVsFullMaxAbsByte"], 0)
            self.assertTrue(report["allSelectedVsFullPsnrInfinite"])
            self.assertEqual(records[0]["selectedVsFull"]["exactPixelFraction"], 1.0)
            self.assertEqual(records[0]["beforeVsFull"]["changedPixelFraction"], 1.0)

    def test_nonzero_selected_error_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            campaign = Path(directory) / "campaign"
            write_case(
                campaign,
                "case-b",
                (0, 0, 0),
                (10, 10, 10),
                (9, 10, 10),
            )
            rows = [
                {
                    "case_id": "case-b",
                    "scene_id": "scene-b",
                    "fallback_full": False,
                    "coupling_regime": "high",
                    "planner_work": 100.0,
                    "full_work": 100.0,
                }
            ]
            (campaign / "campaign-rows.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows)
            )
            report, records = mod.evaluate(campaign, rows, {})
            self.assertEqual(report["selectedExactCases"], 0)
            self.assertEqual(records[0]["selectedVsFull"]["maxAbsByte"], 1)
            self.assertFalse(records[0]["selectedVsFull"]["psnrInfinite"])
            self.assertGreater(records[0]["selectedVsFull"]["psnrDb"], 40.0)

    def test_fallback_final_output_is_full_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            campaign = Path(directory) / "campaign"
            write_case(
                campaign,
                "case-fallback",
                (0, 0, 0),
                (10, 10, 10),
                (0, 0, 0),
            )
            rows = [
                {
                    "case_id": "case-fallback",
                    "scene_id": "scene-fallback",
                    "fallback_full": True,
                    "coupling_regime": "high",
                    "planner_work": 100.0,
                    "full_work": 100.0,
                }
            ]
            (campaign / "campaign-rows.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows)
            )
            report, records = mod.evaluate(campaign, rows, {})
            self.assertEqual(report["selectedExactCases"], 1)
            self.assertEqual(records[0]["selectedVsFull"]["maxAbsByte"], 0)
            self.assertGreater(records[0]["candidateRepairVsFull"]["maxAbsByte"], 0)
            self.assertEqual(records[0]["selectedImageSource"], "full-after-fallback")


    def test_broad_rows_use_explicit_dataset_and_edit_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            campaign = Path(directory) / "campaign"
            write_case(
                campaign,
                "case-rotation",
                (0, 0, 0),
                (30, 20, 10),
                (30, 20, 10),
            )
            rows = [
                {
                    "case_id": "case-rotation",
                    "scene_id": "scannetpp::scene-a",
                    "dataset_id": "scannetpp",
                    "representation": "scannetpp-dslr-colmap-seeded-gaussians",
                    "edit_family": "rotation",
                    "fallback_full": False,
                    "coupling_regime": "medium",
                    "planner_work": 20.0,
                    "full_work": 100.0,
                }
            ]
            report, records = mod.evaluate(campaign, rows, {})
            self.assertEqual(records[0]["dataset"], "scannetpp")
            self.assertEqual(records[0]["editFamily"], "rotation")
            self.assertIn("scannetpp", report["byDataset"])
            self.assertIn("rotation", report["byEditFamily"])
            self.assertEqual(report["byEditFamily"]["rotation"]["cases"], 1)

    def test_grid_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            campaign = Path(directory) / "campaign"
            write_case(campaign, "a", (0, 0, 0), (20, 20, 20), (20, 20, 20))
            write_case(campaign, "b", (0, 0, 0), (40, 40, 40), (40, 40, 40))
            rows = [
                {
                    "case_id": "a",
                    "scene_id": "s1",
                    "fallback_full": False,
                    "coupling_regime": "low",
                    "planner_work": 10.0,
                    "full_work": 100.0,
                },
                {
                    "case_id": "b",
                    "scene_id": "s2",
                    "fallback_full": False,
                    "coupling_regime": "low",
                    "planner_work": 20.0,
                    "full_work": 100.0,
                },
            ]
            (campaign / "campaign-rows.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows)
            )
            _, records = mod.evaluate(campaign, rows, {})
            output = Path(directory) / "grid.png"
            chosen = mod.render_grid(campaign, records, output)
            self.assertTrue(output.is_file())
            self.assertEqual(set(chosen), {"a", "b"})


if __name__ == "__main__":
    unittest.main()
