from __future__ import annotations

import importlib.util
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/cbrc_prepare_broad_worlds.py"
SPEC = importlib.util.spec_from_file_location("cbrc_prepare_broad_worlds", MODULE_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(mod)


class BroadWorldPreparationTests(unittest.TestCase):
    def test_stable_sample_keeps_endpoints(self):
        values = [Path(f"{i:02d}.jpg") for i in range(20)]
        sampled = mod.stable_sample(values, 5)
        self.assertEqual(sampled[0], Path("00.jpg"))
        self.assertEqual(sampled[-1], Path("19.jpg"))
        self.assertEqual(len(sampled), 5)

    def test_overlap_preserving_sample_uses_centered_bounded_stride(self):
        values = [Path(f"{i:03d}.jpg") for i in range(100)]
        sampled = mod.overlap_preserving_sample(values, 10, maximum_stride=4)
        indices = [int(path.stem) for path in sampled]
        self.assertEqual(len(indices), 10)
        self.assertLessEqual(max(b - a for a, b in zip(indices, indices[1:])), 4)
        self.assertGreater(indices[0], 0)
        self.assertLess(indices[-1], 99)

    def test_find_model_accepts_colmap_text_or_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "sparse/0"
            model.mkdir(parents=True)
            (model / "points3D.txt").write_text("# points\n")
            self.assertEqual(mod.find_model(root), model)

    def test_bonn_images_follow_rgb_manifest_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rgb = root / "rgb"
            rgb.mkdir()
            for index in range(3):
                (rgb / f"{index}.png").write_bytes(b"x")
            (root / "rgb.txt").write_text(
                "# comment\n"
                "0.0 rgb/2.png\n"
                "0.1 rgb/0.png\n"
                "0.2 rgb/1.png\n"
            )
            values = mod.bonn_images({"root": str(root)}, 20)
            self.assertEqual([p.name for p in values], ["0.png", "1.png", "2.png"])

    def test_model_point_count_reads_colmap_binary_header(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory)
            (model / "points3D.bin").write_bytes(struct.pack("<Q", 73))
            self.assertEqual(mod.model_point_count(model), 73)
            self.assertEqual(mod.usable_model(model), model)

    def test_reconstruct_colmap_retries_with_exhaustive_matching(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            images = []
            for index in range(8):
                image = root / f"{index:02d}.jpg"
                image.write_bytes(b"x")
                images.append(image)

            calls = []
            mapper_calls = 0

            def fake_run(argv, log, cwd=None):
                nonlocal mapper_calls
                calls.append(argv[1] if len(argv) > 1 else argv[0])
                if len(argv) > 1 and argv[1] == "mapper":
                    mapper_calls += 1
                    if mapper_calls == 1:
                        raise RuntimeError("first mapper failed")
                    model = root / "workspace/sparse/0"
                    model.mkdir(parents=True, exist_ok=True)
                    (model / "points3D.bin").write_bytes(struct.pack("<Q", 64))

            with mock.patch.object(mod, "run", side_effect=fake_run):
                model, count = mod.reconstruct_colmap(
                    images,
                    root / "workspace",
                    colmap="/fake/colmap",
                    maximum_images=8,
                    sequential=True,
                )

            self.assertEqual(count, 8)
            self.assertEqual(model, root / "workspace/sparse/0")
            self.assertEqual(mapper_calls, 2)
            self.assertIn("sequential_matcher", calls)
            self.assertIn("exhaustive_matcher", calls)

    def test_stage_images_rejects_too_few_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            values = []
            for index in range(7):
                path = root / f"{index}.jpg"
                path.write_bytes(b"x")
                values.append(path)
            with self.assertRaisesRegex(ValueError, "at least 8"):
                mod.stage_images(values, root / "staged", 20)


if __name__ == "__main__":
    unittest.main()
