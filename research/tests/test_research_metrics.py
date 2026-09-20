import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "metrics" / "research_metrics.py"
SPEC = importlib.util.spec_from_file_location("research_metrics", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class ResearchMetricsTests(unittest.TestCase):
    def test_mixed_work_units_do_not_get_summed_without_cost_weights(self):
        result = MODULE.update_locality_ratio(
            {"gaussian_inspections": 10, "bytes_uploaded": 100},
            {"gaussian_inspections": 100, "bytes_uploaded": 1000},
        )
        self.assertIsNone(result["ratio"])
        self.assertEqual(result["components"]["gaussian_inspections"]["ratio"], 0.1)
        self.assertEqual(result["components"]["bytes_uploaded"]["ratio"], 0.1)

    def test_explicit_cost_weights_enable_aggregate(self):
        result = MODULE.update_locality_ratio(
            {"jobs": 2, "bytes": 100},
            {"jobs": 10, "bytes": 1000},
            {"jobs": 5.0, "bytes": 0.01},
        )
        self.assertAlmostEqual(result["ratio"], 11.0 / 60.0)

    def test_unchanged_world_damage_stays_decomposed(self):
        result = MODULE.unchanged_world_damage(
            [
                {"geometry_displacement": 0.0, "render_absolute_error": 0.01},
                {"geometry_displacement": 0.002, "render_absolute_error": 0.0},
            ]
        )
        self.assertEqual(result["sample_count"], 2)
        self.assertAlmostEqual(result["geometry"]["mean"], 0.001)
        self.assertAlmostEqual(result["render"]["mean"], 0.005)

    def test_identity_survival_counts_switches_and_missing(self):
        result = MODULE.identity_survival(
            {"a": "chair", "b": "wall", "c": "lamp"},
            {"a": "chair", "b": "desk"},
        )
        self.assertEqual(result["correct"], 1)
        self.assertEqual(result["switched"], 1)
        self.assertEqual(result["missing"], 1)


if __name__ == "__main__":
    unittest.main()
