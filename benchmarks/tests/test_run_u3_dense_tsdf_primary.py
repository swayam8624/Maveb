import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "benchmarks" / "scripts" / "run_u3_dense_tsdf_primary.py"
SPEC = importlib.util.spec_from_file_location("run_u3_dense_tsdf_primary", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


class RunU3DenseTsdfPrimaryTests(unittest.TestCase):
    def test_percentile_nearest_uses_tie_lower_rule(self):
        self.assertEqual(runner.nearest_tie_lower_index(3, 0.25), 0)
        self.assertEqual(runner.nearest_tie_lower_index(5, 0.375), 1)
        self.assertEqual(runner.nearest_tie_lower_index(5, 0.5), 2)

    def test_scene_bootstrap_is_deterministic(self):
        values = [0.10, 0.12, 0.20, 0.08, 0.15]
        first = runner.paired_bootstrap_median(values, replicates=200, seed=42)
        second = runner.paired_bootstrap_median(values, replicates=200, seed=42)
        self.assertEqual(first, second)
        self.assertAlmostEqual(first["median"], 0.12, places=12)
        self.assertGreater(first["lower95"], 0.0)

    def test_compact_geometry_metrics_uses_frozen_fscore_threshold(self):
        report = {
            "metrics": {
                "accuracyMean": 0.01,
                "completenessMean": 0.02,
                "chamferMean": 0.015,
                "fScores": [{"threshold": 0.05, "fScore": 0.9}],
            }
        }
        fuse = {
            "elapsedMilliseconds": 12.0,
            "peakResidentBytes": 1024,
            "vertices": 100,
            "triangles": 200,
        }
        compact = runner.compact_geometry_metrics(report, fuse)
        self.assertEqual(compact["chamferMeanMetres"], 0.015)
        self.assertEqual(compact["fScore"], 0.9)


if __name__ == "__main__":
    unittest.main()
