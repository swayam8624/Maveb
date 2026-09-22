from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "research/analysis/cbrc_visual_quality.py"
spec = importlib.util.spec_from_file_location("cbrc_visual_quality", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


class VisualQualityTests(unittest.TestCase):
    def test_pair_metrics_exact_and_changed(self):
        a = np.zeros((4, 5, 3), dtype=np.float64)
        exact = mod.pair_metrics(a, a.copy())
        self.assertEqual(exact.linf, 0.0)
        self.assertIsNone(exact.psnr_db)
        self.assertEqual(exact.exact_pixel_fraction, 1.0)

        b = a.copy()
        b[0, 0, 0] = 1.0
        changed = mod.pair_metrics(a, b)
        self.assertEqual(changed.linf, 1.0)
        self.assertAlmostEqual(changed.changed_pixel_fraction, 1 / 20)
        self.assertIsNotNone(changed.psnr_db)

    def test_campaign_audit_and_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign = root / "campaign"
            output = root / "out"
            rows = []
            for index, (scene, fallback) in enumerate(
                (("tnt-train", False), ("deep-playroom", True))
            ):
                case_id = f"case-{index}"
                visual = campaign / "cases" / case_id / "visuals"
                visual.mkdir(parents=True)

                before = np.zeros((16, 24, 3), dtype=np.uint8)
                full_after = before.copy()
                full_after[2:6, 3:8, :] = 80 + index
                selected = full_after.copy()
                for name, array in (
                    ("before.ppm", before),
                    ("full-after.ppm", full_after),
                    ("selected-repair.ppm", selected),
                ):
                    Image.fromarray(array, "RGB").save(visual / name)

                for name in (
                    "certified-support.ppm",
                    "edit-effect.ppm",
                    "post-repair-residual.ppm",
                ):
                    Image.fromarray(before, "RGB").save(visual / name)

                rows.append(
                    {
                        "case_id": case_id,
                        "scene_id": scene,
                        "coupling_regime": "low",
                        "fallback_full": fallback,
                        "planner_work": 100 if fallback else 30,
                        "full_work": 100,
                        "qois": {
                            "rgb_linf": {
                                "epsilon": 0.01,
                                "certified_bound": 0.001,
                                "measured_full_reference_error": 0.0,
                            }
                        },
                    }
                )

            (campaign / "campaign-rows.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows)
            )
            report = mod.audit(campaign)
            self.assertEqual(report["aggregate"]["case_count"], 2)
            self.assertEqual(report["aggregate"]["scene_count"], 2)
            self.assertEqual(
                report["aggregate"]["selected_matches_full_exactly"],
                2,
            )
            self.assertEqual(
                report["aggregate"]["cases_with_visible_pixel_change"],
                2,
            )

            output.mkdir()
            (output / "visual-quality.json").write_text(json.dumps(report))
            mod.save_csv(report["cases"], output / "visual-quality.csv")
            mod.save_markdown(report, output / "VISUAL_QUALITY.md")
            mod.save_mosaic(
                campaign,
                report["cases"],
                output / "visual-quality-mosaic.png",
            )
            self.assertTrue((output / "visual-quality.csv").is_file())
            self.assertTrue((output / "VISUAL_QUALITY.md").is_file())
            self.assertTrue(
                (output / "visual-quality-mosaic.png").is_file()
            )


if __name__ == "__main__":
    unittest.main()
