from __future__ import annotations
import importlib.util, json, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"scripts/adapters/vgscene_to_temporal_manifest.py"
spec=importlib.util.spec_from_file_location("vgscene_adapter",SCRIPT)
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

class VGSceneAdapterTests(unittest.TestCase):
    def fixture(self,root:Path,kind:str="synthetic")->Path:
        seq=root/"flat1_400"; (seq/"results/rgb").mkdir(parents=True); (seq/"results/depth").mkdir(parents=True)
        for i in range(5):
            (seq/"results/rgb"/f"{i:06d}.png").write_bytes(b"x")
            (seq/"results/depth"/f"{i:06d}.png").write_bytes(b"x")
        (seq/"intrinsic.txt").write_text("500 0 320\n0 500 240\n0 0 1\n")
        (seq/"traj.txt").write_text("0 0 0 0 0 0 0 1\n")
        return seq

    def test_builds_canonical_temporal_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            payload=mod.build(self.fixture(Path(td)),"synthetic")
            self.assertEqual(payload["frameCount"],5)
            self.assertTrue(payload["temporalContract"]["readyForRevisionPartitioning"])
            self.assertEqual(payload["frames"][2]["rgb"],"results/rgb/000002.png")
            self.assertEqual(payload["camera"]["fx"],500.0)

    def test_rejects_unpaired_streams(self):
        with tempfile.TemporaryDirectory() as td:
            seq=self.fixture(Path(td)); (seq/"results/depth/000004.png").unlink()
            with self.assertRaises(ValueError): mod.build(seq,"synthetic")

    def test_rejects_missing_camera_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            seq=self.fixture(Path(td)); (seq/"intrinsic.txt").unlink()
            with self.assertRaises(ValueError): mod.build(seq,"synthetic")

if __name__=="__main__": unittest.main()
