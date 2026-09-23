from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "benchmarks/scripts/cbrc_storage.py"
spec = importlib.util.spec_from_file_location("cbrc_storage_test", SCRIPT)
storage = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(storage)

DOCTOR = ROOT / "benchmarks/scripts/cbrc_storage_doctor.py"
doctor_spec = importlib.util.spec_from_file_location("cbrc_storage_doctor_test", DOCTOR)
doctor = importlib.util.module_from_spec(doctor_spec)
assert doctor_spec.loader
doctor_spec.loader.exec_module(doctor)


class CBRCCampaignStorageTests(unittest.TestCase):
    def test_remove_materialized_world_removes_all_revision_sidecars(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "case.aetherworld"
            files = [
                archive,
                Path(str(archive) + ".gaussians.r1.bin"),
                Path(str(archive) + ".ownership.r1.bin"),
                Path(str(archive) + ".gaussians.r2.bin"),
                Path(str(archive) + ".ownership.r2.bin"),
            ]
            for path in files:
                path.write_bytes(b"x")
            unrelated = root / "keep.txt"
            unrelated.write_text("keep")

            removed = storage.remove_materialized_world(archive)

            self.assertEqual(removed, len(files))
            self.assertTrue(all(not path.exists() for path in files))
            self.assertEqual(unrelated.read_text(), "keep")

    def test_storage_efficient_copy_is_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            destination = root / "destination.bin"
            source.write_bytes(b"original-data")

            mode = storage.copy_storage_efficient(source, destination)

            self.assertIn(mode, {"clone", "copy"})
            self.assertEqual(destination.read_bytes(), b"original-data")
            destination.write_bytes(b"changed")
            self.assertEqual(source.read_bytes(), b"original-data")

    def test_incomplete_freeze_inputs_are_safe_to_remove(self):
        with tempfile.TemporaryDirectory() as directory:
            freeze = Path(directory)
            (freeze / "inputs").mkdir()
            safe, reason = doctor.freeze_inputs_recoverable(freeze)
            self.assertTrue(safe)
            self.assertIn("incomplete", reason)

    def test_complete_freeze_requires_source_worlds(self):
        with tempfile.TemporaryDirectory() as directory:
            freeze = Path(directory)
            source = freeze / "source.aetherworld"
            source.write_text("{}")
            payload = {
                "frozen_inputs": [
                    {
                        "case_id": "case",
                        "source_archive": str(source),
                    }
                ]
            }
            (freeze / "BROAD_CAMPAIGN_FREEZE.json").write_text(
                json.dumps(payload)
            )
            safe, _ = doctor.freeze_inputs_recoverable(freeze)
            self.assertTrue(safe)

            source.unlink()
            safe, _ = doctor.freeze_inputs_recoverable(freeze)
            self.assertFalse(safe)


if __name__ == "__main__":
    unittest.main()
