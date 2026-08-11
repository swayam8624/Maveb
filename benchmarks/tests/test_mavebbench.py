import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "mavebbench.py"
SPEC = importlib.util.spec_from_file_location("mavebbench", MODULE_PATH)
bench = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
import sys
sys.modules[SPEC.name] = bench
SPEC.loader.exec_module(bench)


class MavebBenchTests(unittest.TestCase):
    def test_expand_path_expands_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            os.environ["MAVEB_TEST_DATA"] = directory
            self.assertEqual(bench.expand_path("$MAVEB_TEST_DATA"), Path(directory).resolve())

    def test_report_preserves_adapter_required(self):
        markdown = bench.report_markdown(
            [
                {
                    "dataset": "arkit",
                    "title": "ARKit",
                    "kind": "arkit-scenes",
                    "status": "adapter-required",
                    "steps": [],
                }
            ]
        )
        self.assertIn("adapter-required", markdown)
        self.assertNotIn("**pass**", markdown.lower())

    def test_parse_json_output_uses_last_json_line(self):
        result = bench.CommandResult(
            argv=["tool"],
            returncode=0,
            duration_seconds=0.1,
            stdout="log line\n{\"ok\":true,\"images\":14}\n",
            stderr="",
        )
        self.assertEqual(bench.parse_json_output(result)["images"], 14)

    def test_manifest_ids_match_filenames(self):
        for manifest in bench.iter_manifests():
            self.assertRegex(manifest["id"], r"^[a-z0-9-]+$")
            self.assertEqual(bench.load_manifest(manifest["id"])["id"], manifest["id"])

    def test_image_manifest_resolves(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = {
                "schemaVersion": 1,
                "id": "fixture",
                "title": "Fixture",
                "kind": "images",
                "root": directory,
                "imagesRel": "",
            }
            resolved = bench.resolve_input(manifest)
            self.assertTrue(resolved["ready"])

    def test_missing_video_is_not_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = {
                "schemaVersion": 1,
                "id": "video",
                "title": "Video",
                "kind": "video",
                "root": directory,
                "videoGlob": "**/rgb_video.mp4",
            }
            self.assertFalse(bench.resolve_input(manifest)["ready"])

    def test_metric_reference_is_resolved_for_rgbd_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "depth.bin").write_bytes(b"depth")
            (root / "reference.ply").write_text("ply\n")
            manifest = {
                "schemaVersion": 1,
                "id": "rgbd",
                "title": "RGB-D fixture",
                "kind": "arkit-scenes",
                "root": directory,
                "requiredAssets": {"depth": "depth.bin"},
                "referenceGeometryRel": "reference.ply",
            }
            resolved = bench.resolve_input(manifest)
            self.assertTrue(resolved["ready"])
            self.assertTrue(resolved["referenceReady"])
            self.assertEqual(Path(resolved["referenceGeometry"]), (root / "reference.ply").resolve())


if __name__ == "__main__":
    unittest.main()
