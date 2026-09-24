from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


freeze = load_module(
    "cbrc_freeze_reviewer_stress_v3",
    "benchmarks/scripts/cbrc_freeze_reviewer_stress_v3.py",
)
audit = load_module(
    "cbrc_reviewer_evidence_v3",
    "research/analysis/cbrc_reviewer_evidence_v3.py",
)


class ReviewerStressV3FreezeTests(unittest.TestCase):
    def test_residual_ladder_is_frozen_and_grouped_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archives = []
            candidates = []
            records = []
            for index, dataset in enumerate(("a", "b"), start=1):
                archive = root / f"{dataset}.aetherworld"
                gaussian = root / f"{dataset}.aetherworld.gaussians.r1.bin"
                ownership = root / f"{dataset}.aetherworld.ownership.r1.bin"
                for path in (archive, gaussian, ownership):
                    path.write_bytes(b"x")
                candidate = freeze.base.Candidate(
                    archive=archive,
                    revision=1,
                    timestamp=index * 1_000_000,
                    entities={index: {"translation": [0.0, 0.0, 0.0]}},
                    gaussian_sidecar=gaussian,
                    ownership_sidecar=ownership,
                    gaussian_count=100,
                    owners=tuple([index] * 100),
                    minimum=(-1.0, -1.0, -1.0),
                    maximum=(1.0, 1.0, 1.0),
                )
                archives.append(archive)
                candidates.append(candidate)
                records.append(
                    {
                        "datasetId": dataset,
                        "sceneId": f"scene-{dataset}",
                        "status": "ready",
                        "world": str(archive),
                        "representation": "test",
                    }
                )

            prepared = {"records": records}

            def fake_copy(candidate, destination, **_kwargs):
                destination.mkdir(parents=True, exist_ok=True)
                target = destination / candidate.archive.name
                target.write_bytes(b"x")
                return target

            with (
                mock.patch.object(freeze.base, "discover", return_value=(candidates, [])),
                mock.patch.object(freeze.base, "copy_before_state", side_effect=fake_copy),
                mock.patch.object(
                    freeze.base,
                    "derive_camera",
                    return_value={"width": 4, "height": 4},
                ),
                mock.patch.object(freeze.base, "scene_scale", return_value=2.0),
                mock.patch.object(freeze.base, "sha256", return_value="hash"),
            ):
                campaign, provenance = freeze.build(
                    prepared,
                    root / "out",
                    scenes_per_dataset=1,
                    work_cost_model=None,
                    epsilon_levels_255=(1.0, 4.0),
                    residual_scales=(0.0, 1.0 / 256.0),
                )

            self.assertEqual(campaign["protocol"], "post-reviewer-graded-residual-v3")
            self.assertEqual(campaign["residualScales"], [0.0, 1.0 / 256.0])
            self.assertEqual(provenance["residualScales"], [0.0, 1.0 / 256.0])

            groups = {}
            for case in campaign["cases"]:
                key = case["matrix_tags"]["stress_key"]
                groups.setdefault(key, []).append(case)

            self.assertTrue(groups)
            for cases in groups.values():
                self.assertEqual(len(cases), 2)
                residuals = {case["reviewer_repair_residual_scale"] for case in cases}
                self.assertEqual(len(residuals), 1)
                eps = {case["epsilon"] for case in cases}
                self.assertEqual(len(eps), 2)
                self.assertTrue(
                    all(case["matrix_tags"]["repair_omit_fraction"] == 0.0 for case in cases)
                )

    def test_residual_ladder_requires_exact_control(self):
        with self.assertRaises(ValueError):
            freeze.build(
                {"records": []},
                Path("/tmp/not-used"),
                scenes_per_dataset=1,
                work_cost_model=None,
                residual_scales=(1.0 / 256.0,),
            )


class ReviewerEvidenceV3Tests(unittest.TestCase):
    def test_graded_residual_counts_as_certified_partial_repair(self):
        campaign = {
            "protocol": "post-reviewer-graded-residual-v3",
            "cases": [
                {
                    "id": "full",
                    "dataset_id": "3rscan",
                    "source_scene_id": "s1",
                    "representation": "test",
                    "coupling_regime": "high",
                    "edit_family": "translation",
                    "matrix_tags": {
                        "stress_key": "k",
                        "severity_profile": "strong",
                        "repair_residual_scale": 1.0 / 256.0,
                        "epsilon_255": 1.0,
                        "naturalChangePair": "reference__rescan",
                    },
                },
                {
                    "id": "local",
                    "dataset_id": "3rscan",
                    "source_scene_id": "s1",
                    "representation": "test",
                    "coupling_regime": "high",
                    "edit_family": "translation",
                    "matrix_tags": {
                        "stress_key": "k",
                        "severity_profile": "strong",
                        "repair_residual_scale": 1.0 / 256.0,
                        "epsilon_255": 4.0,
                        "naturalChangePair": "reference__rescan",
                    },
                },
            ],
        }
        rows = [
            {
                "case_id": "full",
                "scene_id": "3rscan::s1",
                "fallback_full": True,
                "planner_work": 10.0,
                "full_work": 10.0,
                "qois": {
                    "rgb_linf": {
                        "epsilon": 1.0 / 255.0,
                        "certified_bound": 0.0,
                        "measured_full_reference_error": 0.0,
                    }
                },
                "candidateDiagnostics": {
                    "candidateActualRgbError": 2.0 / 255.0,
                    "candidateRgbBound": 3.0 / 255.0,
                    "repairMode": "certified-graded-residual-v1",
                    "repairResidualScaleRequested": 1.0 / 256.0,
                    "repairOmittedGaussians": 0,
                    "repairAppliedChangedGaussians": 100,
                    "repairCertificateViolationPixels": 0,
                },
            },
            {
                "case_id": "local",
                "scene_id": "3rscan::s1",
                "fallback_full": False,
                "planner_work": 4.0,
                "full_work": 10.0,
                "qois": {
                    "rgb_linf": {
                        "epsilon": 4.0 / 255.0,
                        "certified_bound": 3.0 / 255.0,
                        "measured_full_reference_error": 2.0 / 255.0,
                    }
                },
                "candidateDiagnostics": {
                    "candidateActualRgbError": 2.0 / 255.0,
                    "candidateRgbBound": 3.0 / 255.0,
                    "affectedPixelFraction": 0.2,
                    "repairMode": "certified-graded-residual-v1",
                    "repairResidualScaleRequested": 1.0 / 256.0,
                    "repairOmittedGaussians": 0,
                    "repairAppliedChangedGaussians": 100,
                    "repairCertificateViolationPixels": 0,
                },
            },
        ]
        report, records = audit.analyze(rows, campaign)
        self.assertEqual(report["certifiedPartialRepairCases"], 2)
        self.assertTrue(report["readinessGates"]["hasCertifiedPartialRepairMode"])
        self.assertEqual(report["certifiedNonzeroLocalCases"], 1)
        self.assertEqual(report["toleranceCrossoverGroups"], 1)
        self.assertEqual(records[1]["repairResidualScale"], 1.0 / 256.0)


if __name__ == "__main__":
    unittest.main()
