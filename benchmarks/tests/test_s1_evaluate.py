from __future__ import annotations
import importlib.util, unittest
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1]/"scripts/s1_evaluate.py"
spec=importlib.util.spec_from_file_location("s1_eval",SCRIPT)
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

class S1EvaluationTests(unittest.TestCase):
    def test_healthy_sparse_locality_passes(self):
        result=mod.evaluate(mod.synthetic(True))
        self.assertTrue(result["pass"])
        self.assertEqual(result["hiddenGlobalLayers"],[])
        self.assertTrue(result["gates"]["G6FullReferenceObserved"])

    def test_hidden_global_scan_is_detected(self):
        result=mod.evaluate(mod.synthetic(False))
        self.assertFalse(result["pass"])
        self.assertIn("tsdfBlocksRead",result["hiddenGlobalLayers"])

    def test_equivalence_failure_blocks_claim(self):
        rows=mod.synthetic(True); rows[1]["equivalence"]["pass"]=False
        result=mod.evaluate(rows)
        self.assertFalse(result["gates"]["G2Equivalence"])
        self.assertFalse(result["pass"])

if __name__=="__main__": unittest.main()
