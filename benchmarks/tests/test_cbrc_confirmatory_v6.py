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
    "cbrc_freeze_confirmatory_v6",
    "benchmarks/scripts/cbrc_freeze_confirmatory_v6.py",
)
breadth = load_module(
    "cbrc_v6_breadth_analysis",
    "research/analysis/cbrc_v6_breadth_analysis.py",
)
packet = load_module(
    "cbrc_v6_manuscript_packet",
    "research/analysis/cbrc_v6_manuscript_packet.py",
)


class ConfirmatoryV6ProtocolTests(unittest.TestCase):
    def test_v6_keeps_v5_factor_grid_and_expands_only_scene_breadth(self):
        self.assertEqual(
            freeze.EXPECTED_DATASETS,
            (
                "3rscan",
                "arkitscenes",
                "bonn-rgbd-dynamic",
                "graphdeco-pretrained-3dgs",
            ),
        )
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

    def test_expected_cases_per_scene_is_frozen(self):
        per_scene = (
            len(freeze.SEVERITY_PROFILES)
            * len(freeze.EDIT_FAMILIES)
            * len(freeze.RESIDUAL_SCALES)
            * len(freeze.EPSILON_LEVELS_255)
        )
        self.assertEqual(per_scene, 192)
        self.assertEqual(
            per_scene * 5 * len(freeze.EXPECTED_DATASETS),
            3840,
        )

    def test_runner_shell_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(ROOT / "run_confirmatory_breadth_v6.sh")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class ConfirmatoryV6AnalysisTests(unittest.TestCase):
    def test_scene_bootstrap_is_scene_level_and_deterministic(self):
        values = [0.1, 0.2, 0.3, 0.4, 0.5]
        first = breadth.scene_bootstrap_mean(values, replicates=2000, seed=1904)
        second = breadth.scene_bootstrap_mean(values, replicates=2000, seed=1904)
        self.assertEqual(first, second)
        self.assertEqual(first["scenes"], 5)
        self.assertAlmostEqual(first["mean"], 0.3)
        self.assertGreater(first["ci95"][0], 0.0)

    def test_scene_metrics_keep_opacity_and_translation_paired(self):
        records = []
        for dataset, scene in (("a", "s1"), ("b", "s2")):
            records.extend(
                [
                    {
                        "dataset": dataset,
                        "sourceSceneId": scene,
                        "editFamily": "opacity",
                        "repairResidualScale": 1.0 / 1024.0,
                        "nonzeroLocal": True,
                        "stressKey": f"{dataset}::{scene}::opacity::r1of1024",
                        "postRepairActualRgbError": 0.002,
                        "postRepairResidualBound": 0.003,
                        "productionResolvedRgbBound": 0.001,
                        "epsilon": 0.02,
                        "repairLegacyEnvelopeCounterfactualComputed": True,
                        "repairLegacyEnvelopeBound": 0.05,
                        "workRatioFull": 0.25,
                        "nearBoundaryLocal": False,
                        "certificateOk": True,
                        "repairCertificateViolationPixels": 0,
                    },
                    {
                        "dataset": dataset,
                        "sourceSceneId": scene,
                        "editFamily": "translation",
                        "repairResidualScale": 1.0 / 1024.0,
                        "nonzeroLocal": False,
                        "stressKey": f"{dataset}::{scene}::translation::r1of1024",
                        "postRepairActualRgbError": 0.002,
                        "postRepairResidualBound": 0.2,
                        "workRatioFull": 1.0,
                        "nearBoundaryLocal": False,
                        "certificateOk": True,
                        "repairCertificateViolationPixels": 0,
                    },
                ]
            )
        crossovers = [
            {
                "dataset": "a",
                "sourceSceneId": "s1",
                "editFamily": "opacity",
            }
        ]
        table = breadth.build_scene_metrics(records, crossovers)
        self.assertEqual(len(table), 2)
        by_scene = {row["scene"]: row for row in table}
        self.assertEqual(by_scene["s1"]["opacityNonzeroLocalRate"], 1.0)
        self.assertEqual(by_scene["s1"]["translationNonzeroLocalRate"], 0.0)
        self.assertEqual(by_scene["s1"]["pairedNonzeroLocalRateDelta"], 1.0)
        self.assertEqual(by_scene["s1"]["opacityCrossoverStressKeys"], 1)
        self.assertEqual(by_scene["s2"]["opacityCrossoverStressKeys"], 0)
        self.assertEqual(by_scene["s1"]["casesRescuedByDeltaCertificate"], 1)
        self.assertEqual(by_scene["s2"]["casesRescuedByDeltaCertificate"], 1)
        self.assertEqual(by_scene["s1"]["legacyCounterfactualCoveredCases"], 1)

    def test_manuscript_packet_is_gated_by_confirmatory_pass(self):
        audit = {
            "confirmatoryPass": False,
            "sceneCount": 20,
            "datasetCount": 4,
            "pooledCaseCount": 3840,
            "sceneClustered": {
                "pairedOpacityMinusTranslationNonzeroLocalRate": {
                    "mean": 0.25,
                    "ci95": [0.10, 0.40],
                },
                "scenesWithNonzeroOpacityLocal": 15,
                "scenesWithOpacityCrossover": 10,
                "datasetsWithNonzeroOpacityLocal": ["a", "b", "c", "d"],
                "sameOpacityLegacyEnvelopeAblation": {
                    "counterfactualCoverageComplete": True,
                    "deltaCertificateRescueRate": {
                        "scenes": 20,
                        "mean": 0.20,
                        "ci95": [0.10, 0.30],
                    },
                    "medianSceneLegacyToDeltaResidualBoundRatio": 8.0,
                    "scenesWithAtLeastOneRescuedCase": 15,
                },
                "certificateTightness": {
                    "medianOfSceneMedianResidualEffectivity": 3.0,
                    "medianOfSceneMaximumActualToEpsilon": 0.55,
                    "maximumSceneMaximumActualToEpsilon": 0.82,
                    "pooledNearBoundaryLocalCases": 2,
                },
            },
            "certificateAudit": {"certificateExperimentValid": True},
            "confirmatoryGates": {"example": False},
            "scientificBoundary": "scene-clustered only",
            "baselineSceneSummary": {},
        }
        blocked = packet.build(audit)
        self.assertFalse(blocked["promotable"])

        audit["confirmatoryPass"] = True
        audit["confirmatoryGates"] = {"example": True}
        promoted = packet.build(audit)
        self.assertTrue(promoted["promotable"])
        self.assertEqual(promoted["claims"]["independentSceneCount"], 20)

    def test_baseline_scene_summary_does_not_pool_scenes(self):
        rows = [
            {
                "scene_id": "a::s1",
                "dataset_id": "a",
                "baselines": {
                    "CBRC": {
                        "passes": True,
                        "usedFullRebuild": False,
                        "workRatioFull": 0.25,
                    },
                    "FULL": {
                        "passes": True,
                        "usedFullRebuild": True,
                        "workRatioFull": 1.0,
                    },
                },
                "ablations": {},
            },
            {
                "scene_id": "b::s2",
                "dataset_id": "b",
                "baselines": {
                    "CBRC": {
                        "passes": True,
                        "usedFullRebuild": False,
                        "workRatioFull": 0.50,
                    },
                    "FULL": {
                        "passes": True,
                        "usedFullRebuild": True,
                        "workRatioFull": 1.0,
                    },
                },
                "ablations": {},
            },
        ]
        table, summary = breadth.baseline_scene_metrics(rows)
        self.assertEqual(len(table), 4)
        self.assertEqual(summary["baselines:CBRC"]["scenes"], 2)
        self.assertAlmostEqual(
            summary["baselines:CBRC"]["medianSceneWorkRatioFull"],
            0.375,
        )
        self.assertEqual(
            summary["baselines:FULL"]["medianSceneWorkRatioFull"],
            1.0,
        )


if __name__ == "__main__":
    unittest.main()
