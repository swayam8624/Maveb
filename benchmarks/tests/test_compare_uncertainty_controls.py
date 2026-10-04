import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "compare_uncertainty_controls.py"
SPEC = importlib.util.spec_from_file_location("compare_uncertainty_controls", MODULE_PATH)
compare = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = compare
SPEC.loader.exec_module(compare)


class CompareUncertaintyControlsTests(unittest.TestCase):
    def report(self, path: Path, student_t_values, correlations):
        groups = []
        for index, scene in enumerate(("a", "b", "c")):
            groups.append(
                {
                    "group": {"scene": scene, "method": "m"},
                    "metrics": {
                        "studentTNll": student_t_values[index],
                        "gaussianNll": student_t_values[index] + 1.0,
                        "expectedCalibrationErrorMetres": 0.01 + 0.001 * index,
                        "pearsonSigmaAbsoluteError": correlations[index],
                        "sharpnessRmsSigmaMetres": 0.02,
                        "empiricalRmseMetres": 0.03 + 0.001 * index,
                    },
                }
            )
        path.write_text(json.dumps({"schemaVersion": 2, "groups": groups}))

    def test_paired_scene_bootstrap_is_deterministic_and_directional(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            intact_path = root / "intact.json"
            control_path = root / "control.json"
            self.report(intact_path, [-2.0, -2.1, -1.9], [0.4, 0.5, 0.3])
            self.report(control_path, [-1.5, -1.6, -1.4], [0.1, 0.2, 0.0])
            intact = compare.load_scene_metrics(intact_path)
            control = compare.load_scene_metrics(control_path)
            first = compare.compare(
                intact, control, control_name="shuffled", replicates=256, seed=42
            )
            second = compare.compare(
                intact, control, control_name="shuffled", replicates=256, seed=42
            )
            self.assertEqual(first, second)
            tnll = first["comparisons"]["studentTNll"]
            self.assertLess(tnll["meanDifference"], 0.0)
            self.assertEqual(tnll["intactBetterSceneCount"], 3)
            corr = first["comparisons"]["pearsonSigmaAbsoluteError"]
            self.assertGreater(corr["meanDifference"], 0.0)
            self.assertEqual(corr["intactBetterSceneCount"], 3)

    def test_comparison_rejects_changed_empirical_errors(self):
        intact = {
            "a": {
                "studentTNll": -2.0,
                "gaussianNll": -1.0,
                "expectedCalibrationErrorMetres": 0.01,
                "pearsonSigmaAbsoluteError": 0.3,
                "sharpnessRmsSigmaMetres": 0.02,
                "empiricalRmseMetres": 0.03,
            }
        }
        control = {"a": {**intact["a"], "empiricalRmseMetres": 0.04}}
        with self.assertRaisesRegex(ValueError, "changed empirical error samples"):
            compare.compare(intact, control, control_name="constant", replicates=16, seed=1)


if __name__ == "__main__":
    unittest.main()
