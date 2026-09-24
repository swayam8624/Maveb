from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "benchmarks/scripts/cbrc_broad_benchmark.py"
SPEC = importlib.util.spec_from_file_location("cbrc_broad_benchmark", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BroadDatasetAutodiscoveryTests(unittest.TestCase):
    def dataset(self):
        return {
            "id": "arkitscenes",
            "kind": "arkit-scenes",
            "rootEnv": "MAVEB_ARKITSCENES",
            "dataSubdirs": ["ARKitScenes", "arkitscenes"],
        }

    def test_explicit_dataset_environment_override_wins(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            explicit = root / "explicit"
            canonical = root / "data" / "ARKitScenes"
            explicit.mkdir(parents=True)
            canonical.mkdir(parents=True)
            with patch.dict(
                os.environ,
                {
                    "MAVEB_ARKITSCENES": str(explicit),
                    "MAVEB_DATA": str(root / "data"),
                },
                clear=False,
            ):
                self.assertEqual(MODULE.configured_root(self.dataset()), explicit.resolve())

    def test_maveb_data_canonical_directory_is_discovered(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            canonical = root / "ARKitScenes"
            canonical.mkdir()
            with patch.dict(os.environ, {"MAVEB_DATA": str(root)}, clear=False):
                os.environ.pop("MAVEB_ARKITSCENES", None)
                self.assertEqual(
                    MODULE.configured_root(self.dataset()),
                    canonical.resolve(),
                )

    def test_alias_directory_is_discovered(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            alias = root / "arkitscenes"
            alias.mkdir()
            with patch.dict(os.environ, {"MAVEB_DATA": str(root)}, clear=False):
                os.environ.pop("MAVEB_ARKITSCENES", None)
                discovered = MODULE.configured_root(self.dataset())
                self.assertIsNotNone(discovered)
                self.assertTrue(discovered.samefile(alias))

    def test_missing_dataset_remains_unconfigured(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"MAVEB_DATA": temp}, clear=False):
                os.environ.pop("MAVEB_ARKITSCENES", None)
                self.assertIsNone(MODULE.configured_root(self.dataset()))


if __name__ == "__main__":
    unittest.main()
