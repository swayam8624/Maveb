import importlib.util
from pathlib import Path
import unittest


def load_module(name: str, filename: str):
    path = Path(__file__).resolve().parents[1] / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


model = load_module("geometric_uncertainty", "geometric_uncertainty.py")
metrics = load_module("uncertainty_metrics", "uncertainty_metrics.py")


class GeometricUncertaintyTests(unittest.TestCase):
    def base_observation(self):
        return model.UncertaintyObservation(
            depth_metres=2.0,
            sensor_confidence=1.0,
            pose_confidence=1.0,
            reprojection_error_pixels=0.0,
            focal_length_pixels=1000.0,
        )

    def test_uncertainty_increases_with_depth(self):
        near = model.predict_uncertainty(self.base_observation())
        far_observation = model.UncertaintyObservation(
            **{**self.base_observation().__dict__, "depth_metres": 4.0}
        )
        far = model.predict_uncertainty(far_observation)
        self.assertGreater(far.sigma_metres, near.sigma_metres)
        self.assertLess(far.precision_weight, near.precision_weight)

    def test_uncertainty_increases_when_sensor_confidence_falls(self):
        high = model.predict_uncertainty(self.base_observation())
        low_observation = model.UncertaintyObservation(
            **{**self.base_observation().__dict__, "sensor_confidence": 0.25}
        )
        low = model.predict_uncertainty(low_observation)
        self.assertGreater(low.sensor_sigma_metres, high.sensor_sigma_metres)
        self.assertGreater(low.sigma_metres, high.sigma_metres)

    def test_alignment_rotation_contributes_metric_error(self):
        clean = model.predict_uncertainty(self.base_observation())
        rotated_observation = model.UncertaintyObservation(
            **{
                **self.base_observation().__dict__,
                "alignment_orientation_error_degrees": 2.0,
            }
        )
        rotated = model.predict_uncertainty(rotated_observation)
        self.assertGreater(rotated.alignment_rotation_sigma_metres, 0.0)
        self.assertGreater(rotated.sigma_metres, clean.sigma_metres)

    def test_invalid_confidence_is_rejected(self):
        invalid = model.UncertaintyObservation(
            **{**self.base_observation().__dict__, "pose_confidence": 1.1}
        )
        with self.assertRaises(ValueError):
            model.predict_uncertainty(invalid)


class UncertaintyMetricsTests(unittest.TestCase):
    def test_perfect_rms_calibration_has_zero_ece(self):
        samples = [
            metrics.ErrorSample(0.01, 0.01),
            metrics.ErrorSample(0.01, -0.01),
            metrics.ErrorSample(0.02, 0.02),
            metrics.ErrorSample(0.02, -0.02),
        ]
        result = metrics.evaluate(samples, bin_count=2)
        self.assertAlmostEqual(result["expectedCalibrationErrorMetres"], 0.0, places=12)
        self.assertAlmostEqual(result["coverage1Sigma"], 1.0)
        self.assertAlmostEqual(result["coverage2Sigma"], 1.0)
        self.assertAlmostEqual(result["pearsonSigmaAbsoluteError"], 1.0)

    def test_overconfident_predictions_are_exposed(self):
        samples = [
            metrics.ErrorSample(0.01, 0.10),
            metrics.ErrorSample(0.01, -0.10),
        ]
        result = metrics.evaluate(samples, bin_count=1)
        self.assertAlmostEqual(result["expectedCalibrationErrorMetres"], 0.09, places=12)
        self.assertEqual(result["coverage1Sigma"], 0.0)
        self.assertEqual(result["coverage2Sigma"], 0.0)
        self.assertIsNone(result["pearsonSigmaAbsoluteError"])

    def test_jsonl_parser_rejects_zero_sigma(self):
        with self.assertRaises(ValueError):
            metrics.parse_jsonl(['{"predictedSigmaMetres":0,"signedErrorMetres":0.01}'])

    def test_bootstrap_is_deterministic(self):
        samples = [
            metrics.ErrorSample(0.01, 0.008),
            metrics.ErrorSample(0.02, -0.018),
            metrics.ErrorSample(0.03, 0.025),
            metrics.ErrorSample(0.04, -0.05),
        ]
        first = metrics.bootstrap_intervals(samples, replicates=64, seed=7)
        second = metrics.bootstrap_intervals(samples, replicates=64, seed=7)
        self.assertEqual(first, second)
        self.assertIn("expectedCalibrationErrorMetres", first)

    def test_grouping_keeps_scene_as_evidence_unit(self):
        samples = [
            metrics.ErrorSample(0.01, 0.01, scene="a", method="u", view_count=8),
            metrics.ErrorSample(0.01, -0.01, scene="b", method="u", view_count=8),
        ]
        groups = metrics.grouped_evaluation(samples, bin_count=1)
        self.assertEqual(len(groups), 2)
        self.assertEqual({record["group"]["scene"] for record in groups}, {"a", "b"})


if __name__ == "__main__":
    unittest.main()
