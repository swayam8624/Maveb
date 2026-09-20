import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
MODULE_PATH = ROOT / "research" / "tools" / "expand_experiment_matrix.py"
SPEC = importlib.util.spec_from_file_location("expand_experiment_matrix", MODULE_PATH)
matrix_tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(matrix_tool)


class ExperimentMatrixTests(unittest.TestCase):
    def test_campaign_matrix_is_deterministic_and_complete(self):
        matrix = json.loads(
            (ROOT / "research" / "config" / "s1_minimal_repair_matrix.json").read_text()
        )
        first = matrix_tool.expand(matrix)
        second = matrix_tool.expand(matrix)
        self.assertEqual(first, second)
        expected = (
            len(matrix["datasets"])
            * len(matrix["methods"])
            * len(matrix["changedFractions"])
            * len(matrix["resourceBudgets"])
        )
        self.assertEqual(len(first), expected)
        self.assertEqual(len({run["configHash"] for run in first}), expected)
        for run in first:
            self.assertIn("gpuPublicationBytes", run["requiredMetrics"]["requiredLocalityDomains"])
            self.assertIn("temporalPixelsInvalidated", run["requiredMetrics"]["requiredLocalityDomains"])


if __name__ == "__main__":
    unittest.main()
