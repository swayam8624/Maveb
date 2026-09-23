from __future__ import annotations

import importlib.util
import json
import subprocess
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
    "cbrc_freeze_reviewer_stress",
    "benchmarks/scripts/cbrc_freeze_reviewer_stress.py",
)
audit = load_module(
    "cbrc_reviewer_evidence",
    "research/analysis/cbrc_reviewer_evidence.py",
)
try:
    visuals = load_module(
        "cbrc_reviewer_visuals",
        "research/analysis/cbrc_reviewer_visuals.py",
    )
except ModuleNotFoundError as error:
    if error.name != "PIL":
        raise
    visuals = None


class ReviewerStressFreezeTests(unittest.TestCase):
    def test_scene_selection_is_deterministic_and_result_independent(self):
        records = [
            {
                "datasetId": "a",
                "sceneId": "scene-2",
                "status": "ready",
                "world": "/tmp/a2.aetherworld",
            },
            {
                "datasetId": "a",
                "sceneId": "scene-1",
                "status": "ready",
                "world": "/tmp/a1.aetherworld",
            },
            {
                "datasetId": "b",
                "sceneId": "scene-9",
                "status": "ready",
                "world": "/tmp/b9.aetherworld",
            },
        ]
        first = freeze.select_records(records, scenes_per_dataset=1)
        second = freeze.select_records(list(reversed(records)), scenes_per_dataset=1)
        self.assertEqual(
            [(item["datasetId"], item["sceneId"]) for item in first],
            [(item["datasetId"], item["sceneId"]) for item in second],
        )
        self.assertEqual(len(first), 2)

    def test_epsilon_ladder_changes_only_epsilon_within_stress_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "scene.aetherworld"
            gaussian = root / "scene.aetherworld.gaussians.r1.bin"
            ownership = root / "scene.aetherworld.ownership.r1.bin"
            archive2 = root / "scene2.aetherworld"
            gaussian2 = root / "scene2.aetherworld.gaussians.r1.bin"
            ownership2 = root / "scene2.aetherworld.ownership.r1.bin"
            for path in (
                archive,
                gaussian,
                ownership,
                archive2,
                gaussian2,
                ownership2,
            ):
                path.write_bytes(b"x")

            candidate = freeze.base.Candidate(
                archive=archive,
                revision=1,
                timestamp=1_000_000,
                entities={7: {"translation": [0.0, 0.0, 0.0]}},
                gaussian_sidecar=gaussian,
                ownership_sidecar=ownership,
                gaussian_count=100,
                owners=tuple([7] * 100),
                minimum=(-1.0, -1.0, -1.0),
                maximum=(1.0, 1.0, 1.0),
            )
            candidate2 = freeze.base.Candidate(
                archive=archive2,
                revision=1,
                timestamp=2_000_000,
                entities={8: {"translation": [0.1, 0.0, 0.0]}},
                gaussian_sidecar=gaussian2,
                ownership_sidecar=ownership2,
                gaussian_count=100,
                owners=tuple([8] * 100),
                minimum=(-1.0, -1.0, -1.0),
                maximum=(1.0, 1.0, 1.0),
            )
            prepared = {
                "records": [
                    {
                        "datasetId": "testset",
                        "sceneId": "scene",
                        "status": "ready",
                        "world": str(archive),
                        "representation": "test",
                    },
                    {
                        "datasetId": "testset2",
                        "sceneId": "scene2",
                        "status": "ready",
                        "world": str(archive2),
                        "representation": "test",
                    },
                ]
            }

            def fake_copy(_candidate, destination, **_kwargs):
                destination.mkdir(parents=True, exist_ok=True)
                target = destination / "scene.aetherworld"
                target.write_bytes(b"x")
                return target

            with (
                mock.patch.object(
                    freeze.base,
                    "discover",
                    return_value=([candidate, candidate2], []),
                ),
                mock.patch.object(freeze.base, "copy_before_state", side_effect=fake_copy),
                mock.patch.object(freeze.base, "derive_camera", return_value={"width": 4, "height": 4}),
                mock.patch.object(freeze.base, "scene_scale", return_value=2.0),
                mock.patch.object(freeze.base, "sha256", return_value="hash"),
            ):
                campaign, _ = freeze.build(
                    prepared,
                    root / "out",
                    scenes_per_dataset=1,
                    work_cost_model=None,
                    epsilon_levels_255=(0.5, 1.0),
                )

            groups = {}
            for case in campaign["cases"]:
                groups.setdefault(case["matrix_tags"]["stress_key"], []).append(case)

            self.assertTrue(groups)
            for cases in groups.values():
                self.assertEqual(len(cases), 2)
                first, second = cases
                self.assertNotEqual(first["epsilon"], second["epsilon"])
                first_revision = dict(first["revision"])
                second_revision = dict(second["revision"])
                first_revision.pop("archive")
                second_revision.pop("archive")
                self.assertEqual(first_revision, second_revision)


class ReviewerStressRunnerTests(unittest.TestCase):
    def test_runner_shell_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(ROOT / "run_reviewer_stress_campaign.sh")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(visuals is None, "Pillow is not installed in this CI environment")
    def test_crossover_visual_smoke(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "crossover.png"
            report = {
                "records": [
                    {
                        "stressKey": "k",
                        "dataset": "3rscan",
                        "sourceSceneId": "scene",
                        "editFamily": "translation",
                        "severityProfile": "strong",
                        "epsilon255": 0.5,
                        "local": False,
                        "nonzeroLocal": False,
                        "actual": 0.0,
                    },
                    {
                        "stressKey": "k",
                        "dataset": "3rscan",
                        "sourceSceneId": "scene",
                        "editFamily": "translation",
                        "severityProfile": "strong",
                        "epsilon255": 2.0,
                        "local": True,
                        "nonzeroLocal": True,
                        "actual": 1.0 / 255.0,
                        "actualToEpsilon": 0.5,
                    },
                ],
                "crossoverGroups": [{"stressKey": "k"}],
            }
            result = visuals.render_crossover(report, output)
            self.assertTrue(output.is_file())
            self.assertEqual(result["stressKeys"], ["k"])


class ReviewerEvidenceAuditTests(unittest.TestCase):
    def test_detects_nonzero_local_and_full_to_local_crossover(self):
        campaign = {
            "protocol": "test",
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
                        "epsilon_255": 0.5,
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
                        "epsilon_255": 2.0,
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
                        "epsilon": 0.5 / 255.0,
                        "certified_bound": 0.0,
                        "measured_full_reference_error": 0.0,
                    }
                },
                "candidateDiagnostics": {
                    "candidateActualRgbError": 1.0 / 255.0,
                    "candidateRgbBound": 1.5 / 255.0,
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
                        "epsilon": 2.0 / 255.0,
                        "certified_bound": 1.5 / 255.0,
                        "measured_full_reference_error": 1.0 / 255.0,
                    }
                },
                "candidateDiagnostics": {
                    "candidateActualRgbError": 1.0 / 255.0,
                    "candidateRgbBound": 1.5 / 255.0,
                    "affectedPixelFraction": 0.2,
                },
            },
        ]
        report, records = audit.analyze(rows, campaign)
        self.assertEqual(report["certifiedNonzeroLocalCases"], 1)
        self.assertEqual(report["toleranceCrossoverGroups"], 1)
        self.assertEqual(report["dynamicCapturedSceneCandidates"], 1)
        self.assertEqual(report["capturedChangeContextCandidates"], 1)
        self.assertTrue(report["readinessGates"]["hasCapturedChangeContext"])
        self.assertTrue(records[1]["certificateOk"])
        self.assertTrue(records[1]["nonzeroLocal"])


if __name__ == "__main__":
    unittest.main()
