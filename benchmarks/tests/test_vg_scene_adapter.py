import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "adapters" / "vg_scene_index.py"
SPEC = importlib.util.spec_from_file_location("vg_scene_index", MODULE_PATH)
vg = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(vg)


class VgSceneAdapterTests(unittest.TestCase):
    def make_real(self, root: Path) -> Path:
        seq = root / "ldyn_real" / "room_2"
        (seq / "rgb").mkdir(parents=True)
        (seq / "depth").mkdir()
        for i in range(4):
            (seq / "rgb" / f"{i}.png").write_bytes(b"rgb")
            (seq / "depth" / f"{i}.png").write_bytes(b"depth")
        (seq / "rgb.txt").write_text("\n".join(f"{i}.0 rgb/{i}.png" for i in range(4)) + "\n")
        (seq / "depth.txt").write_text("\n".join(f"{i}.0 depth/{i}.png" for i in range(4)) + "\n")
        (seq / "groundtruth.txt").write_text(
            "\n".join(f"{i}.0 0 0 0 0 0 0 1" for i in range(4)) + "\n"
        )
        return seq

    def make_synthetic(self, root: Path) -> Path:
        seq = root / "ldyn_syn" / "flat_2"
        results = seq / "results"
        results.mkdir(parents=True)
        (seq / "intrinsic.txt").write_text("1 0 0 0\n")
        (seq / "traj.txt").write_text("0 0 0\n")
        for i in range(4):
            (results / f"frame{i:06d}.jpg").write_bytes(b"rgb")
            (results / f"depth{i:06d}.png").write_bytes(b"depth")
        return seq

    def test_indexes_real_and_synthetic_revision_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_real(root)
            self.make_synthetic(root)
            result = vg.discover(root)
            self.assertEqual(result["sequenceCount"], 2)
            by_id = {row["id"]: row for row in result["sequences"]}
            self.assertEqual(by_id["room_2"]["preChangeFrames"], 2)
            self.assertEqual(by_id["room_2"]["postChangeFrames"], 2)
            self.assertEqual(by_id["flat_2"]["preChangeFrames"], 2)
            self.assertEqual(by_id["flat_2"]["format"], "replica-style")

    def test_missing_depth_frame_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seq = self.make_real(root)
            (seq / "depth" / "3.png").unlink()
            with self.assertRaises(ValueError):
                vg.discover(root)

    def test_out_of_range_change_boundary_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seq = root / "ldyn_syn" / "flat_9"
            results = seq / "results"
            results.mkdir(parents=True)
            (seq / "intrinsic.txt").write_text("1\n")
            (seq / "traj.txt").write_text("1\n")
            for i in range(4):
                (results / f"frame{i:06d}.jpg").write_bytes(b"x")
                (results / f"depth{i:06d}.png").write_bytes(b"x")
            with self.assertRaises(ValueError):
                vg.discover(root)


if __name__ == "__main__":
    unittest.main()
