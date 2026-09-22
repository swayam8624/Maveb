from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/cbrc_broad_benchmark.py"
SPEC = importlib.util.spec_from_file_location("cbrc_broad_benchmark", MODULE_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(mod)


class BroadBenchmarkImporterTests(unittest.TestCase):
    def test_graphdeco_discovers_all_requested_scene_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scene = root / "garden"
            ply = scene / "point_cloud/iteration_30000/point_cloud.ply"
            ply.parent.mkdir(parents=True)
            ply.write_bytes(b"ply\n")
            (scene / "cameras.json").write_text("[]\n")
            spec = {
                "id": "graphdeco-pretrained-3dgs",
                "kind": "trained-3dgs",
                "role": "primary",
                "selection": {"scenes": ["garden"]},
                "redistribute": False,
            }
            result = mod.graphdeco(spec, root)
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["readyScenes"], 1)
            self.assertEqual(result["scenes"][0]["sceneId"], "garden")
            self.assertTrue(result["scenes"][0]["pointCloud"].endswith("point_cloud.ply"))

    def test_3rscan_freezes_changed_reference_rescan_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for scan_id in ("reference", "rescan"):
                scan = root / scan_id
                scan.mkdir()
                for name in (
                    "mesh.refined.v2.obj",
                    "semseg.v2.json",
                    "labels.instances.annotated.v2.ply",
                ):
                    (scan / name).write_text("{}\n")
                (scan / "sequence").mkdir()
            (root / "3RScan.json").write_text(
                json.dumps(
                    [
                        {
                            "reference": "reference",
                            "type": "validation",
                            "scans": [
                                {
                                    "reference": "rescan",
                                    "transform": list(range(16)),
                                    "rigid": [{"instance_reference": 4, "instance_rescan": 4}],
                                    "removed": [9],
                                    "nonrigid": [],
                                }
                            ],
                        }
                    ]
                )
            )
            spec = {
                "id": "3rscan",
                "kind": "longitudinal-rgbd",
                "role": "natural",
                "metadata": "3RScan.json",
                "scanRequired": [
                    "mesh.refined.v2.obj",
                    "semseg.v2.json",
                    "labels.instances.annotated.v2.ply",
                ],
                "sequenceAny": ["sequence", "sequence.zip"],
                "selection": {
                    "preferredSplit": "val",
                    "targetPairs": 40,
                    "minimumRigidOrRemovedChanges": 1,
                },
                "redistribute": False,
            }
            result = mod.three_r_scan(spec, root)
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["selectedPairs"], 1)
            self.assertEqual(result["scenes"][0]["changeCount"], 2)

    def test_scannetpp_uses_frozen_split(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "split").mkdir()
            (root / "split/nvs_sem_val.txt").write_text("scene_a\nscene_b\n")
            for scene_id in ("scene_a", "scene_b"):
                scene = root / "data" / scene_id
                (scene / "scans").mkdir(parents=True)
                (scene / "dslr/colmap").mkdir(parents=True)
                (scene / "scans/mesh_aligned_0.05.ply").write_bytes(b"ply")
                (scene / "dslr/train_test_lists.json").write_text("{}\n")
            spec = {
                "id": "scannetpp",
                "kind": "scannetpp",
                "role": "sensor",
                "selection": {"split": "nvs_sem_val", "targetScenes": 2},
                "required": [
                    "scans/mesh_aligned_0.05.ply",
                    "dslr/colmap",
                    "dslr/train_test_lists.json",
                ],
                "redistribute": False,
            }
            result = mod.scannetpp(spec, root)
            self.assertEqual(result["status"], "ready")
            self.assertEqual([s["sceneId"] for s in result["scenes"]], ["scene_a", "scene_b"])

    def test_arkit_and_bonn_discovery_are_structure_based(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arkit_root = root / "arkit/video_001"
            arkit_root.mkdir(parents=True)
            (arkit_root / "lowres_wide.traj").write_text("0 0 0 0 0 0 0\n")
            for name in ("lowres_depth", "lowres_wide", "lowres_wide_intrinsics"):
                (arkit_root / name).mkdir()
            arkit_spec = {
                "id": "arkitscenes",
                "kind": "arkit-scenes",
                "role": "mobile",
                "selection": {"targetVideos": 20},
                "requiredAny": [
                    "lowres_wide.traj",
                    "lowres_depth",
                    "lowres_wide",
                    "lowres_wide_intrinsics",
                ],
                "redistribute": False,
            }
            self.assertEqual(mod.arkit(arkit_spec, root / "arkit")["status"], "ready")

            bonn_root = root / "bonn/rgbd_bonn_test"
            bonn_root.mkdir(parents=True)
            for name in ("rgb.txt", "depth.txt", "groundtruth.txt"):
                (bonn_root / name).write_text("# header\n0.0 value\n")
            bonn_spec = {
                "id": "bonn-rgbd-dynamic",
                "kind": "tum-rgbd",
                "role": "dynamic",
                "selection": {"targetSequences": 12},
                "required": ["rgb.txt", "depth.txt", "groundtruth.txt"],
                "camera": {"fx": 1, "fy": 1, "cx": 0, "cy": 0},
                "redistribute": False,
            }
            result = mod.bonn(bonn_spec, root / "bonn")
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["scenes"][0]["rgbRows"], 1)


if __name__ == "__main__":
    unittest.main()
