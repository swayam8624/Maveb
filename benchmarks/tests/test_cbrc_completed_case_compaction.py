from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


compactor = load(
    "cbrc_compact_completed_cases",
    "benchmarks/scripts/cbrc_compact_completed_cases.py",
)
campaign = load("cbrc_campaign_compaction_test", "benchmarks/scripts/cbrc_campaign.py")


class CompletedCaseCompactionTests(unittest.TestCase):
    def make_complete_case(self, root: Path) -> Path:
        case_dir = root / "cases/case-a"
        case_dir.mkdir(parents=True)
        payloads = {
            "CASE_COMPLETE.json": {
                "caseId": "case-a",
                "executionSignature": "signature-a",
                "timing": {"case_wall_ms": 1.0},
            },
            "replay-manifest.json": {"git_sha": "abc"},
            "revision-row.json": {"case_id": "case-a"},
            "baselines.json": {"case_id": "case-a"},
            "provenance.json": {"artifact": "provenance"},
        }
        for name, payload in payloads.items():
            (case_dir / name).write_text(json.dumps(payload), encoding="utf-8")

        visuals = case_dir / "visuals"
        visuals.mkdir()
        (visuals / "before.ppm").write_bytes(b"x" * 1024)
        capture = case_dir / "capture"
        capture.mkdir()
        (capture / "translation.json").write_bytes(b"y" * 2048)
        (case_dir / "spatial-evidence.csv").write_bytes(b"z" * 4096)
        (case_dir / "evaluation.json").write_text("{}", encoding="utf-8")
        return case_dir

    def test_execute_keeps_resume_core_and_removes_heavy_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            case_dir = self.make_complete_case(root)
            _, reclaimed = compactor.compact_case(case_dir, execute=True)
            self.assertGreater(reclaimed, 0)

            for name in compactor.REQUIRED_FILES:
                self.assertTrue((case_dir / name).is_file())
            self.assertTrue((case_dir / "provenance.json").is_file())
            self.assertFalse((case_dir / "visuals").exists())
            self.assertFalse((case_dir / "capture").exists())
            self.assertFalse((case_dir / "spatial-evidence.csv").exists())

            marker = json.loads(
                (case_dir / "CASE_COMPLETE.json").read_text(encoding="utf-8")
            )
            self.assertTrue(marker["evidenceCompacted"])
            self.assertGreater(marker["reclaimedBytes"], 0)

            reused = campaign.reusable_case(
                case_dir,
                case_id="case-a",
                signature="signature-a",
                git_sha="abc",
                adopt_existing=False,
            )
            self.assertIsNotNone(reused)

    def test_dry_run_changes_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            case_dir = self.make_complete_case(root)
            before = compactor.path_size(case_dir)
            _, reclaimable = compactor.compact_case(case_dir, execute=False)
            self.assertGreater(reclaimable, 0)
            self.assertEqual(before, compactor.path_size(case_dir))
            self.assertTrue((case_dir / "visuals/before.ppm").is_file())

    def test_incomplete_case_is_never_compacted_as_complete(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            case_dir = root / "cases/partial"
            case_dir.mkdir(parents=True)
            (case_dir / "visuals.ppm").write_bytes(b"x" * 4096)
            report = compactor.compact_root(
                root,
                execute=True,
                purge_incomplete=False,
            )
            self.assertEqual(report["completedCases"], 0)
            self.assertEqual(report["incompleteCases"], 1)
            self.assertTrue(case_dir.exists())

    def test_explicit_purge_removes_only_incomplete_case_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            complete = self.make_complete_case(root)
            partial = root / "cases/partial"
            partial.mkdir(parents=True)
            (partial / "broken.ppm").write_bytes(b"x" * 4096)
            report = compactor.compact_root(
                root,
                execute=True,
                purge_incomplete=True,
            )
            self.assertTrue(complete.exists())
            self.assertFalse(partial.exists())
            self.assertGreater(report["purgedIncompleteBytes"], 0)


if __name__ == "__main__":
    unittest.main()
