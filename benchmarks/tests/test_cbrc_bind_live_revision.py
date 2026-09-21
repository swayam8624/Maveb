from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/cbrc_bind_live_revision.py"
spec = importlib.util.spec_from_file_location("cbrc_bind_live_revision", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def translation():
    return {
        "previousRevision": 4,
        "revision": 5,
        "gaussianCount": 100,
        "beforeGaussianSidecar": "/tmp/world.gaussians.r4.bin",
        "afterGaussianSidecar": "/tmp/world.gaussians.r5.bin",
        "gaussianInputFormat": "aether-bin",
        "translatedGaussians": 4,
        "gaussiansInspected": 12,
        "persisted": True,
    }


def certificate():
    return {
        "available": True,
        "revisionVersion": 3,
        "changedGaussians": 4,
        "affectedPixelRatio": 0.15,
        "maximumCurrentRgbBound": 0.02,
        "invalidationCoversCertifiedSupport": True,
        "temporalFullFrameFallback": False,
        "outputConePlanner": {
            "available": True,
            "stable": True,
            "passes": True,
            "temporalValidationStable": True,
            "temporalRepairSelected": False,
            "fullRepair": False,
            "resolvedRgbBound": 0.018,
            "epsilon": 0.03,
            "historyWeight": 0.9,
            "temporalRepairWork": 256,
            "plannerWork": 0,
            "fullWork": 2048,
        },
        "camera": {
            "width": 64,
            "height": 32,
            "focalX": 45.0,
            "focalY": 45.0,
            "centerX": 32.25,
            "centerY": 15.75,
            "near": 0.01,
            "far": 1000.0,
            "cameraWorldPosition": [1, 2, 3],
            "worldToCamera": [
                1, 0, 0, -1,
                0, 1, 0, -2,
                0, 0, 1, -3,
                0, 0, 0, 1,
            ],
        },
        "publication": {
            "touchedBytes": 1024,
            "fullBufferBytes": 25600,
        },
        "temporal": {
            "invalidatedPixels": 256,
            "fullFramePixels": 2048,
        },
    }


class CBRCLiveRevisionBinderTests(unittest.TestCase):
    def test_frozen_version_identifiers(self):
        self.assertEqual(
            mod.GAUSSIAN_OUTPUT_GRAPH_VERSION,
            "gaussian-output-cone-v2",
        )
        self.assertEqual(
            mod.GAUSSIAN_TEMPORAL_BOUND_VERSION,
            "gaussian-image-temporal-v1",
        )

    def test_binds_exact_revision_sidecars_and_camera(self):
        result = mod.bind(
            translation(),
            certificate(),
            scene_id="scene",
            git_sha="abc",
            epsilon=0.03,
        )
        self.assertEqual(result["input_format"], "aether-bin")
        self.assertTrue(result["detect_changed"])
        self.assertEqual(result["revision_id"], "4->5")
        self.assertEqual(result["camera"]["center_x"], 32.25)
        self.assertEqual(result["hard_closure_nodes"], 4)
        self.assertEqual(
            result["work_ledger"]["domains"]["gpuPublicationBytes"]["incremental"],
            1024,
        )
        self.assertEqual(
            result["execution_mode"], "hybrid-supplied-source-planner-output"
        )
        graph = result["output_planner_graph"]
        self.assertEqual(graph["full_work_baseline"], 2048)
        self.assertEqual(
            graph["qois"][0]["weights"]["temporal_history"], 0.9
        )
        self.assertEqual(graph["hard_closure"], ["current_frame"])
        self.assertEqual(result["native_scalar_work"]["candidate"], 0)
        self.assertEqual(result["native_scalar_work"]["full"], 2048)
        self.assertEqual(result["native_scalar_work"]["unit"], "temporal-pixels")

    def test_output_planner_epsilon_mismatch_fails_closed(self):
        c = certificate()
        c["outputConePlanner"]["epsilon"] = 0.01
        with self.assertRaisesRegex(ValueError, "epsilon disagrees"):
            mod.bind(
                translation(),
                c,
                scene_id="scene",
                git_sha="abc",
                epsilon=0.03,
            )

    def test_unstable_temporal_validation_hardens_history(self):
        c = certificate()
        c["outputConePlanner"]["temporalValidationStable"] = False
        c["outputConePlanner"]["historyWeight"] = 1.0
        c["outputConePlanner"]["temporalRepairSelected"] = True
        c["outputConePlanner"]["plannerWork"] = 2048
        result = mod.bind(
            translation(),
            c,
            scene_id="scene",
            git_sha="abc",
            epsilon=0.03,
        )
        self.assertEqual(
            result["output_planner_graph"]["hard_closure"],
            ["current_frame", "temporal_history"],
        )

    def test_changed_count_disagreement_fails_closed(self):
        c = certificate()
        c["changedGaussians"] = 5
        with self.assertRaisesRegex(ValueError, "disagrees"):
            mod.bind(
                translation(),
                c,
                scene_id="scene",
                git_sha="abc",
                epsilon=0.03,
            )

    def test_unpersisted_revision_is_rejected(self):
        t = translation()
        t["persisted"] = False
        with self.assertRaisesRegex(ValueError, "not durably persisted"):
            mod.bind(
                t,
                certificate(),
                scene_id="scene",
                git_sha="abc",
                epsilon=0.03,
            )


if __name__ == "__main__":
    unittest.main()
