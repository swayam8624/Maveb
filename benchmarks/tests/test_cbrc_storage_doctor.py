from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module():
    path = ROOT / "benchmarks/scripts/cbrc_storage_doctor.py"
    spec = importlib.util.spec_from_file_location("cbrc_storage_doctor", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


doctor = load_module()


class StorageDoctorV6CleanupTests(unittest.TestCase):
    def make_repo(self, *, ready_per_dataset: int = 5, failed: int = 0) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        repo = Path(temporary.name)
        smoke = repo / "build/broad-benchmark-smoke"
        smoke.mkdir(parents=True)
        (smoke / "development.bin").write_bytes(b"smoke")

        manifest_dir = repo / "build/broad-benchmark-paper/worlds"
        manifest_dir.mkdir(parents=True)
        records = []
        worlds = repo / "paper-worlds"
        worlds.mkdir()
        for dataset in doctor.V6_CONFIRMATORY_DATASETS:
            for index in range(ready_per_dataset):
                world = worlds / f"{dataset}-{index}.aether"
                world.write_bytes(b"world")
                records.append(
                    {
                        "datasetId": dataset,
                        "sceneId": f"{dataset}-{index}",
                        "status": "ready",
                        "world": str(world),
                    }
                )
        (manifest_dir / "BROAD_WORLDS.json").write_text(
            json.dumps(
                {
                    "readyWorlds": len(records),
                    "failedWorlds": failed,
                    "blockedWorlds": 0,
                    "records": records,
                }
            ),
            encoding="utf-8",
        )
        return repo

    def test_smoke_cache_safe_only_with_complete_clean_v6_paper_worlds(self):
        repo = self.make_repo()
        safe, reason = doctor.smoke_development_tree_recoverable(repo)
        self.assertTrue(safe)
        self.assertIn("superseded development cache", reason)

    def test_smoke_cache_kept_when_any_v6_dataset_has_fewer_than_five_worlds(self):
        repo = self.make_repo(ready_per_dataset=4)
        safe, reason = doctor.smoke_development_tree_recoverable(repo)
        self.assertFalse(safe)
        self.assertIn("lacks five ready v6 scenes", reason)

    def test_smoke_cache_kept_when_paper_manifest_has_failures(self):
        repo = self.make_repo(failed=1)
        safe, reason = doctor.smoke_development_tree_recoverable(repo)
        self.assertFalse(safe)
        self.assertIn("not clean", reason)

    def test_smoke_cache_kept_when_referenced_paper_world_is_missing(self):
        repo = self.make_repo()
        manifest_path = repo / "build/broad-benchmark-paper/worlds/BROAD_WORLDS.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        first = payload["records"][0]
        Path(first["world"]).unlink()
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")

        safe, reason = doctor.smoke_development_tree_recoverable(repo)
        self.assertFalse(safe)
        self.assertIn("lacks five ready v6 scenes", reason)


if __name__ == "__main__":
    unittest.main()
