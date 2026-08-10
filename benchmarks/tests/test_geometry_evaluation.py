import importlib.util,sys,tempfile,unittest
from pathlib import Path
MODULE_PATH=Path(__file__).resolve().parents[1]/"scripts/evaluate_geometry.py"; SPEC=importlib.util.spec_from_file_location("evaluate_geometry",MODULE_PATH); geometry=importlib.util.module_from_spec(SPEC); assert SPEC.loader; sys.modules[SPEC.name]=geometry; SPEC.loader.exec_module(geometry)
class GeometryEvaluationTests(unittest.TestCase):
    def test_fscore(self):
        r=geometry.f_score([0.,.01],[0.,.01],.02); self.assertEqual(r["precision"],1.); self.assertEqual(r["recall"],1.); self.assertEqual(r["fScore"],1.)
    def test_percentile(self): self.assertEqual(geometry.percentile([1,2,3,4,5],.95),5.)
    def test_umeyama(self):
        import numpy as np
        s=np.asarray([[0,0,0],[1,0,0],[0,2,0],[0,0,3]],float); rot=np.asarray([[0,-1,0],[1,0,0],[0,0,1]],float); scale=2.5; tr=np.asarray([4,-3,7],float); target=(scale*rot@s.T).T+tr; transform,recovered=geometry.umeyama_similarity(s,target); aligned=(transform[:3,:3]@s.T).T+transform[:3,3]; self.assertAlmostEqual(recovered,scale,places=8); self.assertTrue(np.allclose(aligned,target,atol=1e-8))
    def test_parse_colmap(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"images.txt"; p.write_text("# Image list\n1 1 0 0 0 0 0 0 1 image.jpg\n10 20 -1\n"); c=geometry.parse_colmap_camera_centers(p); self.assertIn("image.jpg",c); self.assertEqual(tuple(c["image.jpg"]),(0.,0.,0.))
if __name__=="__main__": unittest.main()
