from __future__ import annotations
import importlib.util,tempfile,unittest,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

matrix=load("matrix",ROOT/"scripts/s1_matrix.py")
figures=load("figures",ROOT/"scripts/s1_figures.py")
evalmod=load("evalmod",ROOT/"scripts/s1_evaluate.py")

class S1EvidenceInfrastructureTests(unittest.TestCase):
 def test_matrix_is_frozen_and_complete(self):
  m=matrix.build(); self.assertEqual(m["cellCount"],750); self.assertIn(1.0,m["frozenFactors"]["changedFractions"])
 def test_svg_contains_every_layer(self):
  result=evalmod.evaluate(evalmod.synthetic(True)); svg=figures.render(result)
  self.assertTrue(svg.startswith("<svg"))
  for layer in evalmod.REQUIRED_LAYERS: self.assertIn(layer,svg)

if __name__=="__main__": unittest.main()
