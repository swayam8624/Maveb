#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SCRIPT = SCRIPTS / "run_u4a_anchored_support.py"
spec = importlib.util.spec_from_file_location("run_u4a_anchored_support", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class U4aRunnerTests(unittest.TestCase):
    def test_frozen_method_order(self):
        self.assertEqual(
            module.METHODS,
            (
                "depth-only-anchored-support",
                "calibrated-anchored-support",
                "shuffled-calibrated-anchored-support",
            ),
        )

    def test_relative_improvement_sign(self):
        self.assertAlmostEqual(module.relative_improvement(1.0, 0.9), 0.1)
        self.assertAlmostEqual(module.relative_improvement(1.0, 1.1), -0.1)
        with self.assertRaises(ValueError):
            module.relative_improvement(0.0, 0.9)

    def test_bootstrap_is_deterministic(self):
        values = [-0.2, -0.01, 0.0, 0.1, 0.3]
        a = module.paired_bootstrap_median(values, replicates=2000, seed=42)
        b = module.paired_bootstrap_median(values, replicates=2000, seed=42)
        self.assertEqual(a, b)
        self.assertEqual(a["median"], 0.0)
        self.assertEqual(a["replicates"], 2000)
        self.assertEqual(a["seed"], 42)

    def test_topology_import_is_lazy(self):
        self.assertNotIn("open3d", module.__dict__)


if __name__ == "__main__":
    unittest.main()
