import importlib.util
from pathlib import Path
import sys
import tempfile
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


uncertainty = load_module("geometric_uncertainty_fit_test", "geometric_uncertainty.py")
fitter = load_module("fit_metric_uncertainty", "fit_metric_uncertainty.py")


class FitMetricUncertaintyTests(unittest.TestCase):
    def synthetic_samples(self):
        true_config = uncertainty.UncertaintyModelConfig(
            depth_noise_floor_metres=0.012,
            depth_noise_quadratic_metres_per_metre_squared=0.004,
            sensor_confidence_penalty=4.0,
            pose_translation_floor_metres=0.0,
            pose_translation_scale_metres=0.0,
        )
        result = []
        index = 0
        for scene in ("scene-a", "scene-b"):
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
                    result.append(
                        fitter.CalibrationSample(
                            observation=observation,
                            signed_error_metres=sign * sigma,
                            scene=scene,
                            sample_id=f"sample-{index}",
                        )
                    )
                    index += 1
        return result

    def test_vectorized_objective_matches_scalar_oracle(self):
        samples = self.synthetic_samples()
        config = uncertainty.UncertaintyModelConfig(
            depth_noise_floor_metres=0.009,
            depth_noise_quadratic_metres_per_metre_squared=0.003,
            sensor_confidence_penalty=2.75,
        )
        scalar, scalar_by_scene = fitter.scene_balanced_objective(samples, config)
        arrays = fitter.calibration_arrays(samples, config)
        vectorized, vectorized_by_scene = fitter.vectorized_scene_balanced_objective(arrays, config)
        self.assertAlmostEqual(vectorized, scalar, places=12)
        self.assertEqual(set(vectorized_by_scene), set(scalar_by_scene))
        for scene in scalar_by_scene:
            self.assertAlmostEqual(vectorized_by_scene[scene], scalar_by_scene[scene], places=12)

    def test_fitting_improves_scene_balanced_likelihood(self):
        samples = self.synthetic_samples()
        initial = uncertainty.UncertaintyModelConfig()
        before, _ = fitter.scene_balanced_objective(samples, initial)
        fitted, trace = fitter.fit_sensor_terms(samples, initial, rounds=3)
        after, _ = fitter.scene_balanced_objective(samples, fitted)
        self.assertLess(after, before)
        self.assertTrue(trace)

    def test_stable_downsample_is_order_independent(self):
        samples = self.synthetic_samples()
        first = fitter.stable_scene_downsample(samples, maximum_per_scene=5, seed=42)
        second = fitter.stable_scene_downsample(list(reversed(samples)), maximum_per_scene=5, seed=42)
        self.assertEqual(
            [(sample.scene, sample.sample_id) for sample in first],
            [(sample.scene, sample.sample_id) for sample in second],
        )

    def test_scene_split_rejects_leakage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "split.json"
            path.write_text(
                '{"schemaVersion":1,"id":"fixture","frozen":true,'
                '"calibrationScenes":["a"],"heldOutScenes":["a"]}'
            )
            with self.assertRaises(ValueError):
                fitter.load_scene_split(path)

    def test_scene_split_rejects_unfrozen_split(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "split.json"
            path.write_text(
                '{"schemaVersion":1,"id":"fixture","frozen":false,'
                '"calibrationScenes":["a"],"heldOutScenes":["b"]}'
            )
            with self.assertRaisesRegex(ValueError, "frozen"):
                fitter.load_scene_split(path)

    def test_model_config_round_trip(self):
        config = uncertainty.UncertaintyModelConfig(sensor_confidence_penalty=3.25)
        payload = uncertainty.config_to_json(config)
        recovered = uncertainty.config_from_json({"modelConfig": payload})
        self.assertEqual(recovered, config)


if __name__ == "__main__":
    unittest.main()
