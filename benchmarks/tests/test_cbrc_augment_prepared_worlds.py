from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "benchmarks/scripts/cbrc_augment_prepared_worlds.py"
SPEC = importlib.util.spec_from_file_location("cbrc_augment_prepared_worlds", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BoundedPreparedWorldAugmentationTests(unittest.TestCase):
    def record(self, root: Path, dataset: str, scene: str) -> dict[str, str]:
        world = root / f"{dataset}-{scene}.aetherworld"
        world.write_bytes(f"{dataset}:{scene}".encode())
        return {
            "datasetId": dataset,
            "sceneId": scene,
            "status": "ready",
            "world": str(world),
            "preparationPath": "dataset-native-geometry",
        }

    def test_one_fresh_world_is_augmented_to_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fresh = self.record(root, "arkitscenes", "fresh")
            historical = [
                self.record(root, "graphdeco-pretrained-3dgs", "garden"),
                self.record(root, "3rscan", "scan-a"),
                self.record(root, "arkitscenes", "old-arkit"),
                self.record(root, "bonn-rgbd-dynamic", "bonn-a"),
            ]
            payload, datasets = MODULE.build_bounded_set(
                base_payload={"records": [fresh]},
                base_source=root / "fresh.json",
                candidates=[({"records": historical}, root / "paper.json")],
                target_worlds=4,
                minimum_worlds=2,
            )

            self.assertEqual(payload["readyWorlds"], 4)
            self.assertEqual(payload["freshReadyWorlds"], 1)
            self.assertEqual(payload["reusedHistoricalWorlds"], 3)
            self.assertEqual(payload["records"][0]["sceneId"], "fresh")
            self.assertEqual(
                set(datasets),
                {
                    "arkitscenes",
                    "graphdeco-pretrained-3dgs",
                    "3rscan",
                    "bonn-rgbd-dynamic",
                },
            )

    def test_prefers_new_datasets_before_same_dataset_fill(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fresh = self.record(root, "arkitscenes", "fresh")
            candidates = [
                self.record(root, "arkitscenes", "old-a"),
                self.record(root, "graphdeco-pretrained-3dgs", "garden"),
                self.record(root, "arkitscenes", "old-b"),
            ]
            payload, _ = MODULE.build_bounded_set(
                base_payload={"records": [fresh]},
                base_source=root / "fresh.json",
                candidates=[({"records": candidates}, root / "paper.json")],
                target_worlds=2,
                minimum_worlds=2,
            )
            self.assertEqual(
                [record["datasetId"] for record in payload["records"]],
                ["arkitscenes", "graphdeco-pretrained-3dgs"],
            )

    def test_stale_historical_worlds_do_not_count(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fresh = self.record(root, "arkitscenes", "fresh")
            stale = {
                "datasetId": "3rscan",
                "sceneId": "stale",
                "status": "ready",
                "world": str(root / "missing.aetherworld"),
            }
            with self.assertRaises(ValueError):
                MODULE.build_bounded_set(
                    base_payload={"records": [fresh]},
                    base_source=root / "fresh.json",
                    candidates=[({"records": [stale]}, root / "paper.json")],
                    target_worlds=4,
                    minimum_worlds=2,
                )


if __name__ == "__main__":
    unittest.main()
