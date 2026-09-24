from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "benchmarks/scripts/cbrc_select_import.py"
SPEC = importlib.util.spec_from_file_location("cbrc_select_import", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FastImportPreparedWorldFingerprintTests(unittest.TestCase):
    def test_candidate_manifest_hash_is_embedded_in_development_import(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "BROAD_WORLDS.json"
            candidate.write_text('{"records": []}\n', encoding="utf-8")
            payload = {
                "datasets": [
                    {
                        "datasetId": "arkitscenes",
                        "status": "ready",
                        "scenes": [{"sceneId": "one", "status": "ready"}],
                    }
                ]
            }
            env = {
                "MAVEB_BROAD_REUSE_PREPARED_WORLDS": "1",
                "MAVEB_BROAD_PREPARED_WORLD_CANDIDATES": str(candidate),
                "MAVEB_BROAD_FAST_WORLD_TARGET": "4",
            }
            with patch.dict(os.environ, env, clear=False):
                effective, _ = MODULE.select_import(
                    payload,
                    allow_partial=True,
                    source=root / "import.json",
                )

            fingerprints = effective["developmentPreparedWorldCandidates"]
            self.assertEqual(len(fingerprints), 1)
            self.assertEqual(fingerprints[0]["path"], str(candidate.resolve()))
            self.assertEqual(fingerprints[0]["bytes"], candidate.stat().st_size)
            self.assertEqual(len(fingerprints[0]["sha256"]), 64)
            self.assertEqual(effective["developmentPreparedWorldTarget"], 4)


if __name__ == "__main__":
    unittest.main()
