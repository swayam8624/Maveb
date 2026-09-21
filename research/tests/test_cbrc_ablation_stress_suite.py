from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "experiments/cbrc_ablation_stress_suite.py"
spec = importlib.util.spec_from_file_location("cbrc_ablation_stress_suite", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class CBRCAblationStressSuiteTests(unittest.TestCase):
    def test_every_required_mechanism_has_a_separating_stress_case(self):
        result = mod.run()
        self.assertTrue(result["pass"])
        self.assertEqual(result["mechanismCount"], 7)
        self.assertEqual(result["separatedMechanisms"], 7)
        self.assertTrue(result["syntheticMechanismIsolationOnly"])
        self.assertFalse(result["realCampaignReplacement"])
        for case in result["cases"]:
            self.assertTrue(case["separated"], case["mechanism"])


if __name__ == "__main__":
    unittest.main()
