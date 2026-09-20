from __future__ import annotations
import importlib.util, sys, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"scripts/mavebbench.py"
spec=importlib.util.spec_from_file_location("mavebbench_vg",SCRIPT)
mod=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=mod
spec.loader.exec_module(mod)

class MavebBenchVGSceneTests(unittest.TestCase):
    def fixture(self,root:Path)->Path:
        seq=root/"synthetic"/"flat1_400"
        (seq/"results/rgb").mkdir(parents=True)
        (seq/"results/depth").mkdir(parents=True)
        for i in range(3):
            (seq/"results/rgb"/f"{i:06d}.png").write_bytes(b"x")
            (seq/"results/depth"/f"{i:06d}.png").write_bytes(b"x")
        (seq/"intrinsic.txt").write_text("500 0 320\n0 500 240\n0 0 1\n")
        (seq/"traj.txt").write_text("0 0 0 0 0 0 0 1\n")
        return seq

    def test_resolve_and_adapter_subprocess(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); seq=self.fixture(root)
            manifest={
                "schemaVersion":1,"id":"vg-test","title":"VG test","kind":"vg-scene",
                "root":str(root),"sequences":{"real":[],"synthetic":["flat1_400"]}
            }
            resolved=mod.resolve_input(manifest)
            self.assertTrue(resolved["ready"])
            self.assertTrue(resolved["complete"])
            self.assertEqual(resolved["sequences"][0]["path"],str(seq))
            out=root/"canonical.json"
            status,detail=mod.adapt_vgscene(seq,"synthetic",out)
            self.assertEqual(status,"pass",detail)
            self.assertTrue(out.is_file())
            self.assertEqual(detail["payload"]["frameCount"],3)

if __name__=="__main__": unittest.main()
