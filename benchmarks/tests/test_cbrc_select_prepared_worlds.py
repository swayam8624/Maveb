from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "benchmarks/scripts/cbrc_select_prepared_worlds.py"
SPEC = importlib.util.spec_from_file_location("cbrc_select_prepared_worlds", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PreparedWorldSelectionTests(unittest.TestCase):
    def test_filters_stale_and_duplicate_worlds(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "a.aetherworld"
            second = root / "b.aetherworld"
            first.write_bytes(b"a")
            second.write_bytes(b"b")
            payload = {
                "records": [
                    {
                        "datasetId": "graphdeco-pretrained-3dgs",
                        "sceneId": "a",
                        "status": "ready",
                        "world": str(first),
                        "preparationPath": "dataset-native-geometry",
                    },
                    {
                        "datasetId": "graphdeco-pretrained-3dgs",
                        "sceneId": "a-duplicate",
                        "status": "ready",
                        "world": str(first),
                    },
                    {
                        "datasetId": "arkitscenes",
                        "sceneId": "b",
                        "status": "ready",
                        "world": "b.aetherworld",
                        "preparationPath": "rgb-colmap-fallback",
                    },
                    {
                        "datasetId": "stale",
                        "sceneId": "missing",
                        "status": "ready",
                        "world": str(root / "missing.aetherworld"),
                    },
                    {
                        "datasetId": "blocked",
                        "sceneId": "blocked",
                        "status": "blocked",
                    },
                ]
            }
            selected, datasets = MODULE.select_ready_worlds(
                payload,
                root / "BROAD_WORLDS.json",
            )
            self.assertEqual(selected["readyWorlds"], 2)
            self.assertEqual(selected["blockedWorlds"], 0)
            self.assertEqual(selected["failedWorlds"], 0)
            self.assertEqual(
                datasets,
                ["arkitscenes", "graphdeco-pretrained-3dgs"],
            )
            self.assertEqual(selected["nativePreparedWorlds"], 1)
            self.assertEqual(selected["rgbFallbackWorlds"], 1)

    def test_requires_two_existing_worlds(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            only = root / "only.aetherworld"
            only.write_bytes(b"x")
            payload = {
                "records": [
                    {
                        "datasetId": "arkitscenes",
                        "sceneId": "one",
                        "status": "ready",
                        "world": str(only),
                    }
                ]
            }
            with self.assertRaises(ValueError):
                MODULE.select_ready_worlds(payload, root / "BROAD_WORLDS.json")


if __name__ == "__main__":
    unittest.main()
