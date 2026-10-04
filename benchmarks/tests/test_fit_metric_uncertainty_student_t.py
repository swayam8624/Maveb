import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def load_module(name: str, filename: str):
    path = SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


uncertainty = load_module("geometric_uncertainty_student_t_test", "geometric_uncertainty.py")
gaussian_fit = load_module("fit_metric_uncertainty", "fit_metric_uncertainty.py")
robust_fit = load_module("fit_metric_uncertainty_student_t", "fit_metric_uncertainty_student_t.py")


class FitMetricUncertaintyStudentTTests(unittest.TestCase):
    def synthetic_samples(self):
        true_config = uncertainty.UncertaintyModelConfig(
            depth_noise_floor_metres=0.008,
            depth_noise_quadratic_metres_per_metre_squared=0.002,
            sensor_confidence_penalty=3.0,
            pose_translation_floor_metres=0.0,
            pose_translation_scale_metres=0.0,
        )
        result = []
        index = 0
        for scene in ("scene-a", "scene-b", "scene-c"):
            for depth in (0.5, 1.0, 1.5, 2.0, 3.0):
                for confidence in (0.0, 0.5, 1.0):
                    observation = uncertainty.UncertaintyObservation(
                        depth_metres=depth,
                        sensor_confidence=confidence,
                        pose_confidence=1.0,
                        reprojection_error_pixels=0.0,
                        focal_length_pixels=1000.0,
                    )
                    sigma = uncertainty.predict_uncertainty(observation, true_config).sigma_metres
                    sign = -1.0 if index % 2 else 1.0
                    error = sign * sigma
                    if index % 17 == 0:
                        error *= 20.0
                    result.append(
                        gaussian_fit.CalibrationSample(
                            observation=observation,
                            signed_error_metres=error,
                            scene=scene,
                            sample_id=f"sample-{index}",
                        )
                    )
                    index += 1
        return result

    def test_student_t_objective_improves_on_heavy_tailed_fixture(self):
        samples = self.synthetic_samples()
        initial = uncertainty.UncertaintyModelConfig()
        arrays = gaussian_fit.calibration_arrays(samples, initial)
        before, _ = robust_fit.vectorized_student_t_scene_balanced_objective(arrays, initial)
        fitted, trace = robust_fit.fit_sensor_terms_student_t(
            samples,
            initial,
            rounds=3,
            arrays=arrays,
        )
        after, _ = robust_fit.vectorized_student_t_scene_balanced_objective(arrays, fitted)
        self.assertLess(after, before)
        self.assertTrue(trace)

    def test_student_t_sigma_is_parameterized_as_standard_deviation(self):
        import numpy as np

        errors = np.array([0.0, 0.01, -0.02], dtype=np.float64)
        sigma = np.array([0.1, 0.1, 0.1], dtype=np.float64)
        values = robust_fit.student_t_nll_array(errors, sigma, 3.0)
        self.assertEqual(values.shape, errors.shape)
        self.assertTrue(np.all(np.isfinite(values)))
        with self.assertRaisesRegex(ValueError, "> 2"):
            robust_fit.student_t_nll_array(errors, sigma, 2.0)


if __name__ == "__main__":
    unittest.main()
