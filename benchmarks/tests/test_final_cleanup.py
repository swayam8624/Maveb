from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def load_module():
    path = ROOT / "maintenance/final_cleanup.py"
    spec = importlib.util.spec_from_file_location("maveb_final_cleanup", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


cleanup = load_module()


class FinalCleanupTests(unittest.TestCase):
    def test_delete_scope_is_allow_listed(self):
        self.assertEqual(
            cleanup.REPO_DELETE_RELATIVE,
            (
                Path("build"),
                Path(".aether-deps"),
                Path(".venv-maveb"),
            ),
        )
        self.assertIn(Path("Datasets/MAVEB"), cleanup.HOME_DELETE_RELATIVE)
        self.assertIn(Path("Datasets/MavebBench"), cleanup.HOME_DELETE_RELATIVE)
        self.assertIn(
            Path("Datasets/MavebReferenceWorld"),
            cleanup.HOME_DELETE_RELATIVE,
        )
        self.assertIn(
            Path("Desktop/Programming/MavebData"),
            cleanup.HOME_DELETE_RELATIVE,
        )

    def test_targets_never_include_source_tree_or_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "Maveb"
            home = root / "home"
            archive = repo / "final_evidence/maveb-v6"
            repo.mkdir(parents=True)
            home.mkdir()
            targets = cleanup.deletion_targets(repo, home, archive)
            paths = {Path(item["path"]) for item in targets}
            self.assertNotIn(repo, paths)
            self.assertNotIn(repo / "engine", paths)
            self.assertNotIn(repo / "researchpaper", paths)
            self.assertNotIn(archive, paths)

    def test_archive_v6_preserves_mandatory_evidence_before_delete(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            source = repo / cleanup.V6_RELATIVE
            archive = repo / "final_evidence/maveb-v6"
            for relative in (
                Path("analysis/V6_BREADTH_AUDIT.json"),
                Path("analysis/V6_MANUSCRIPT_CLAIMS.json"),
                Path("frozen/reviewer-stress-campaign.json"),
                Path("frozen/REVIEWER_STRESS_FREEZE.json"),
            ):
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"ok": True}), encoding="utf-8")
            rows = source / "campaign/campaign-rows.jsonl"
            rows.parent.mkdir(parents=True, exist_ok=True)
            rows.write_text('{"row": 1}\n', encoding="utf-8")

            copied = cleanup.archive_v6(repo, archive)
            archived = {Path(item["archive"]) for item in copied}
            self.assertIn(
                archive / "analysis/V6_BREADTH_AUDIT.json",
                archived,
            )
            self.assertTrue(
                (archive / "campaign/campaign-rows.jsonl.gz").is_file()
            )

    def test_archive_refuses_when_mandatory_evidence_is_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            (repo / cleanup.V6_RELATIVE).mkdir(parents=True)
            with self.assertRaises(SystemExit):
                cleanup.archive_v6(
                    repo,
                    repo / "final_evidence/maveb-v6",
                )

    def test_repo_cleanup_refuses_tracked_files_inside_delete_target(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            with mock.patch.object(
                cleanup,
                "tracked_under",
                return_value=["build/should-never-be-tracked.bin"],
            ):
                with self.assertRaises(SystemExit):
                    cleanup.verify_repo_delete_targets_untracked(repo)


if __name__ == "__main__":
    unittest.main()
