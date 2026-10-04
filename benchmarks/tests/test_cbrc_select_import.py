from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "benchmarks/scripts/cbrc_select_import.py"
SPEC = importlib.util.spec_from_file_location("cbrc_select_import", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SelectImportTests(unittest.TestCase):
    def payload(self):
        return {
            "schemaVersion": 1,
            "artifact": "maveb-cbrc-broad-benchmark-import",
            "datasets": [
                {
                    "datasetId": "ready",
                    "status": "ready",
                    "scenes": [
                        {"sceneId": "a", "status": "ready"},
                        {"sceneId": "b", "status": "ready"},
                    ],
                },
                {
                    "datasetId": "partial",
                    "status": "partial",
                    "scenes": [
                        {"sceneId": "c", "status": "ready"},
                        {"sceneId": "d", "status": "blocked"},
                    ],
                },
                {
                    "datasetId": "blocked",
                    "status": "blocked",
                    "issues": ["dataset unavailable"],
                    "scenes": [],
                },
            ],
            "readyDatasets": 1,
            "partialDatasets": 1,
            "blockedDatasets": 1,
        }

    def test_strict_mode_rejects_non_ready_dataset_matrix(self):
        with self.assertRaises(SystemExit) as raised:
            MODULE.select_import(
                self.payload(),
                allow_partial=False,
                source=Path("/tmp/import.json"),
            )
        self.assertEqual(raised.exception.code, 2)

    def test_fast_mode_keeps_only_ready_scenes(self):
        effective, selected = MODULE.select_import(
            self.payload(),
            allow_partial=True,
            source=Path("/tmp/import.json"),
        )
        self.assertEqual(selected, ["ready", "partial"])
        self.assertTrue(effective["developmentOnly"])
        self.assertEqual(effective["blockedDatasets"], 0)
        self.assertEqual(effective["partialDatasets"], 0)
        self.assertEqual(
            [item["datasetId"] for item in effective["datasets"]],
            ["ready", "partial"],
        )
        partial = effective["datasets"][1]
        self.assertEqual(partial["status"], "ready")
        self.assertEqual(partial["readyScenes"], 1)
        self.assertEqual(partial["expectedScenes"], 1)
        self.assertEqual([scene["sceneId"] for scene in partial["scenes"]], ["c"])

    def test_fast_mode_rejects_when_nothing_is_ready(self):
        payload = self.payload()
        for item in payload["datasets"]:
            item["status"] = "blocked"
            item["scenes"] = []
        with self.assertRaises(SystemExit) as raised:
            MODULE.select_import(
                payload,
                allow_partial=True,
                source=Path("/tmp/import.json"),
            )
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
