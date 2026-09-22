from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "research/analysis/cbrc_paper_readiness.py"
spec = importlib.util.spec_from_file_location("cbrc_paper_readiness", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


class PaperReadinessTests(unittest.TestCase):
    def test_complete_fixture_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign = root / "campaign"
            campaign.mkdir()
            rows = []
            for i in range(60):
                rows.append(
                    {
                        "case_id": f"c{i}",
                        "scene_id": f"s{i % 4}",
                        "fallback_full": i % 10 == 0,
                        "work_cost_unit": "ms",
                        "work_cost_model_version": "fixture-v1",
                        "qois": {
                            "rgb_linf": {
                                "epsilon": 0.01,
                                "certified_bound": 0.001,
                                "measured_full_reference_error": 0.0005,
                            }
                        },
                        "candidateDiagnostics": {
                            "sourceEditActualRgbError": 0.02,
                        },
                    }
                )
            (campaign / "campaign-rows.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows)
            )
            (campaign / "campaign-timings.jsonl").write_text(
                "".join(json.dumps({"case_id": f"c{i}"}) + "\n" for i in range(60))
            )
            (campaign / "campaign-gates.json").write_text(json.dumps({"pass": True}))
            (campaign / "campaign-evaluation.json").write_text(json.dumps({"pass": True}))

            calibration = root / "cal.json"
            calibration.write_text(
                json.dumps(
                    {
                        "domains": {
                            "gaussiansInspected": {},
                            "gaussiansUpdated": {},
                            "gpuPublicationBytes": {},
                            "temporalPixelsInvalidated": {},
                        }
                    }
                )
            )
            sparse = root / "sparse.json"
            sparse.write_text(
                json.dumps(
                    {
                        "exactSelectionAgreement": True,
                        "minimumInspectionRatio": 0.02,
                    }
                )
            )
            empirical = root / "empirical.json"
            empirical.write_text(
                json.dumps(
                    {
                        "heldoutCases": 40,
                        "heldoutUnsafeFalseLocalRate": 0.1,
                        "safetyGroundTruth": mod.EMPIRICAL_SAFETY_GROUND_TRUTH,
                    }
                )
            )
            visual_root = root / "visual"
            visual_root.mkdir()
            for name in ("hero.png", "overview.svg"):
                (visual_root / name).write_text("fixture")
            visual = visual_root / "VISUAL_PACKAGE.json"
            visual.write_text(
                json.dumps(
                    {
                        "assets": {
                            "hero": "hero.png",
                            "overview": "overview.svg",
                        }
                    }
                )
            )
            visual_quality = root / "visual-quality.json"
            visual_quality.write_text(
                json.dumps(
                    {
                        "rows": 60,
                        "localSelectedExactCases": 54,
                        "maximumSelectedVsFullMaxAbsByte": 0,
                        "records": [
                            {"beforeVsFull": {"changedPixelFraction": 0.02}}
                            for _ in range(60)
                        ],
                    }
                )
            )
            stress = root / "ablation-stress.json"
            stress.write_text(
                json.dumps(
                    {
                        "pass": True,
                        "syntheticMechanismIsolationOnly": True,
                        "mechanismCount": 7,
                        "separatedMechanisms": 7,
                    }
                )
            )
            result = mod.audit(
                campaign,
                calibration,
                sparse,
                empirical,
                visual,
                visual_quality,
                ablation_stress=stress,
            )
            self.assertTrue(result["corePaperEvidenceReady"])
            self.assertTrue(all(result["checks"].values()))
            self.assertEqual(result["sourceEffectEvidenceCases"], 60)
            self.assertEqual(result["nontrivialSourceEffectCases"], 60)
            self.assertEqual(result["nontrivialSourceEffectRate"], 1.0)
            self.assertTrue(result["checks"]["visualQualityAuditPresent"])
            self.assertTrue(result["checks"]["visualQualityCoversCampaign"])
            self.assertTrue(result["checks"]["localSelectedVisualsMatchFull"])
            self.assertTrue(result["checks"]["visualAuditShowsNontrivialEdits"])


if __name__ == "__main__":
    unittest.main()
