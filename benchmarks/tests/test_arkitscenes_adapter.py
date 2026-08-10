import importlib.util, math, struct, sys, unittest
from pathlib import Path
MODULE_PATH=Path(__file__).resolve().parents[1]/"scripts/adapters/arkitscenes_to_aether.py"; SPEC=importlib.util.spec_from_file_location("arkitscenes_to_aether",MODULE_PATH); adapter=importlib.util.module_from_spec(SPEC); assert SPEC.loader; sys.modules[SPEC.name]=adapter; SPEC.loader.exec_module(adapter)
class ARKitScenesAdapterTests(unittest.TestCase):
    def test_identity(self): self.assertEqual(adapter.trajectory_to_camera_to_world([1.,0.,0.,0.,0.,0.,0.]),[1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.,0.,-0.,-0.,-0.,1.])
    def test_translation_inversion(self): self.assertEqual(adapter.trajectory_to_camera_to_world([1.,0.,0.,0.,1.,2.,3.])[12:15],[-1.,-2.,-3.])
    def test_rodrigues(self):
        r=adapter.rodrigues((0.,0.,math.pi/2)); self.assertAlmostEqual(r[0][0],0.,places=6); self.assertAlmostEqual(r[0][1],-1.,places=6); self.assertAlmostEqual(r[1][0],1.,places=6)
    def test_timestamp_tolerance(self): self.assertEqual(adapter.nearest_timestamp(1.014,[1.,1.01,1.02],.0051),1.01); self.assertIsNone(adapter.nearest_timestamp(1.014,[1.,1.01,1.02],.003))
    def test_depth(self):
        out=adapter.depth_to_f32(bytes([0xE8,0x03,0,0]),2); self.assertAlmostEqual(struct.unpack_from("<f",out,0)[0],1.); self.assertEqual(struct.unpack_from("<f",out,4)[0],0.)
if __name__=="__main__": unittest.main()
