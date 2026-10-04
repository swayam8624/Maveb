import importlib.util
from pathlib import Path
import unittest


def load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "uncertainty_controls.py"
    spec = importlib.util.spec_from_file_location("uncertainty_controls", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


controls = load_module()


class UncertaintyControlsTests(unittest.TestCase):
    def rows(self):
        return [
            {"scene": "a", "sampleId": "a1", "sensorConfidence": 0.0},
            {"scene": "a", "sampleId": "a2", "sensorConfidence": 0.5},
            {"scene": "a", "sampleId": "a3", "sensorConfidence": 1.0},
            {"scene": "b", "sampleId": "b1", "sensorConfidence": 0.0},
            {"scene": "b", "sampleId": "b2", "sensorConfidence": 1.0},
        ]

    def test_shuffle_is_deterministic_and_preserves_scene_distribution(self):
        first = controls.shuffled_confidence(self.rows(), 42)
        second = controls.shuffled_confidence(list(reversed(self.rows())), 42)
        by_id_first = {row["sampleId"]: row["sensorConfidence"] for row in first}
        by_id_second = {row["sampleId"]: row["sensorConfidence"] for row in second}
        self.assertEqual(by_id_first, by_id_second)
        for scene in ("a", "b"):
            original = sorted(
                row["sensorConfidence"] for row in self.rows() if row["scene"] == scene
            )
            shuffled = sorted(
                row["sensorConfidence"] for row in first if row["scene"] == scene
            )
            self.assertEqual(original, shuffled)

    def test_shuffle_breaks_identity_when_scene_has_multiple_rows(self):
        result = controls.shuffled_confidence(self.rows(), 42)
        original = {row["sampleId"]: row["sensorConfidence"] for row in self.rows()}
        controlled = {row["sampleId"]: row["sensorConfidence"] for row in result}
        self.assertTrue(any(original[key] != controlled[key] for key in original))

    def test_constant_control_rejects_invalid_value(self):
        with self.assertRaises(ValueError):
            controls.constant_confidence(self.rows(), 1.1)

    def test_parse_rejects_missing_scene(self):
        with self.assertRaises(ValueError):
            controls.parse_rows(['{"sampleId":"x","sensorConfidence":0.5}'])


if __name__ == "__main__":
    unittest.main()
