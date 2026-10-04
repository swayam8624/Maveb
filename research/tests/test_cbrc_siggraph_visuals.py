from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "research/visualization/cbrc_siggraph_visuals.py"
spec = importlib.util.spec_from_file_location("cbrc_siggraph_visuals", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def row(case_id: str, fallback: bool):
    return {
        "case_id": case_id,
        "scene_id": "fixture-scene",
        "revision_id": "1->2",
        "coupling_regime": "adversarial" if fallback else "low",
        "fallback_full": fallback,
        "planner_work": 100.0 if fallback else 10.0,
        "full_work": 100.0,
        "changed_fraction": 0.05,
        "qois": {
            "rgb_linf": {
                "epsilon": 0.01,
                "certified_bound": 0.0 if fallback else 0.001,
                "measured_full_reference_error": 0.0 if fallback else 0.0002,
            }
        },
        "candidateDiagnostics": {
            "sourceEditActualRgbError": 0.2,
        },
        "work_ledger": {
            "domains": {
                "gaussiansInspected": {"incremental": 10, "full": 100},
                "gaussiansUpdated": {"incremental": 5, "full": 100},
                "gpuPublicationBytes": {"incremental": 50, "full": 1000},
                "temporalPixelsInvalidated": {
                    "incremental": 20 if not fallback else 100,
                    "full": 100,
                },
            }
        },
    }


class SiggraphVisualTests(unittest.TestCase):
    def test_visual_package_generates_from_frozen_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign = root / "campaign"
            output = root / "visuals"
            rows = [row("local", False), row("fallback", True)]
            (campaign / "cases").mkdir(parents=True)
            for item in rows:
                visual = campaign / "cases" / item["case_id"] / "visuals"
                visual.mkdir(parents=True)
                for index, name in enumerate(
                    (
                        "before.ppm",
                        "full-after.ppm",
                        "selected-repair.ppm",
                        "certified-support.ppm",
                        "edit-effect.ppm",
                        "post-repair-residual.ppm",
                    )
                ):
                    Image.new(
                        "RGB",
                        (64, 36),
                        (20 + index * 20, 30, 50),
                    ).save(visual / name)

            (campaign / "campaign-rows.jsonl").write_text(
                "".join(json.dumps(item) + "\n" for item in rows)
            )
            (campaign / "baseline-summary.json").write_text(
                json.dumps(
                    {
                        "baselines": {
                            "FULL": {
                                "passRate": 1.0,
                                "medianWorkRatioFull": 1.0,
                            },
                            "CBRC": {
                                "passRate": 1.0,
                                "medianWorkRatioFull": 0.1,
                            },
                        }
                    }
                )
            )

            hero_cases = mod.hero(
                rows,
                campaign,
                output / "figures" / "F0_hero.png",
            )
            mod.chart_sheet(
                rows,
                json.loads((campaign / "baseline-summary.json").read_text()),
                output / "figures" / "F9_evidence_dashboard.png",
            )
            mod.mosaic(
                rows,
                campaign,
                output / "figures" / "F10_case_mosaic.png",
                maximum=2,
            )
            mod.overview_svg(output / "figures" / "F0_system_overview.svg")
            mod.animated_assets(
                rows,
                campaign,
                output / "video" / "MAVEB_teaser.gif",
                output / "video" / "MAVEB_supplementary_cases.gif",
                hero_cases["local"],
                hero_cases["fallback"],
            )
            self.assertEqual(hero_cases["local"], "local")
            self.assertTrue((output / "figures" / "F0_hero.png").is_file())
            self.assertTrue((output / "video" / "MAVEB_teaser.gif").is_file())
            self.assertTrue(
                (output / "video" / "MAVEB_supplementary_cases.gif").is_file()
            )


if __name__ == "__main__":
    unittest.main()
