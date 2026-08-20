#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_u3b_dense_tsdf_confirmatory.py"
spec = importlib.util.spec_from_file_location("run_u3b_dense_tsdf_confirmatory", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class RunU3bConfirmatoryTests(unittest.TestCase):
    def test_engine_mapping_is_exactly_preregistered_method_set(self):
        protocol_path = Path(__file__).resolve().parents[1] / "experiments" / "metric-uncertainty-u3b-relative-confidence-transfer-v1.json"
        protocol = json.loads(protocol_path.read_text())
        protocol_methods = tuple(item["id"] for item in protocol["methods"])
        self.assertEqual(protocol_methods, module.METHODS)
        self.assertEqual(
            module.ENGINE_MAPPING["u3v1-absolute-inverse-variance"],
            ("legacy", "calibrated-inverse-variance"),
        )
        self.assertEqual(
            module.ENGINE_MAPPING["relative-confidence-precision"],
            ("relative", "calibrated-inverse-variance"),
        )
        self.assertEqual(
            module.ENGINE_MAPPING["relative-confidence-shuffled"],
            ("relative", "calibrated-shuffled-confidence"),
        )

    def test_paired_bootstrap_is_deterministic(self):
        values = [0.2, 0.1, -0.1, 0.3, 0.05]
        first = module.paired_bootstrap_median(values, replicates=2000, seed=42)
        second = module.paired_bootstrap_median(values, replicates=2000, seed=42)
        self.assertEqual(first, second)
        self.assertEqual(first["median"], 0.1)

    def test_percentile_uses_nearest_tie_lower(self):
        self.assertEqual(module.percentile_nearest([0.0, 1.0, 2.0], 0.25), 0.0)
        self.assertEqual(module.percentile_nearest([0.0, 1.0, 2.0], 0.75), 1.0)


if __name__ == "__main__":
    unittest.main()
