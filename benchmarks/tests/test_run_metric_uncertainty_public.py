import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_metric_uncertainty_public.py"
SPEC = importlib.util.spec_from_file_location("run_metric_uncertainty_public", MODULE_PATH)
study = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(study)


class MetricUncertaintyPublicStudyTests(unittest.TestCase):
    def test_concatenate_jsonl_is_deterministic_and_skips_blank_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "a.jsonl"
            second = root / "b.jsonl"
            output = root / "combined.jsonl"
            first.write_text('{"sampleId":"a"}\n\n')
            second.write_text('{"sampleId":"b"}\n')
            count = study.concatenate_jsonl([first, second], output)
            self.assertEqual(count, 2)
            self.assertEqual(
                output.read_text().splitlines(),
                ['{"sampleId":"a"}', '{"sampleId":"b"}'],
            )

    def test_annotate_method_preserves_rows_and_sets_method(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            output = root / "annotated.jsonl"
            source.write_text('{"scene":"s","sampleId":"1","signedErrorMetres":0.01}\n')
            count = study.annotate_method(source, output, "u2-ca1m-intact-confidence")
            self.assertEqual(count, 1)
            row = json.loads(output.read_text())
            self.assertEqual(row["scene"], "s")
            self.assertEqual(row["method"], "u2-ca1m-intact-confidence")

    def test_load_split_requires_ca1m_truth_arkit_confidence_and_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "split.json"
            payload = {
                "schemaVersion": 1,
                "frozen": True,
                "source": {
                    "dataset": "CA-1M / Cubify Anything",
                    "confidenceDataset": "ARKitScenes raw",
                },
                "calibrationScenes": ["a", "b", "c"],
                "heldOutScenes": ["d", "e", "f", "g", "h"],
                "sceneMetadata": {},
            }
            path.write_text(json.dumps(payload))
            loaded, _ = study.load_split(path)
            self.assertEqual(loaded["source"]["confidenceDataset"], "ARKitScenes raw")

            payload["heldOutScenes"][0] = "c"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "isolation"):
                study.load_split(path)

            payload["heldOutScenes"][0] = "d"
            payload["source"]["confidenceDataset"] = "CA-1M"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "confidence sidecar"):
                study.load_split(path)

    def test_archive_and_confidence_paths_follow_frozen_metadata(self):
        entry = {
            "ca1mSplit": "val",
            "arkitFold": "Validation",
            "videoId": "45662921",
        }
        self.assertEqual(
            study.archive_path(Path("/data"), entry),
            Path("/data/ca1m-val-45662921.tar"),
        )
        self.assertEqual(
            study.confidence_directory(Path("/confidence"), entry),
            Path("/confidence/raw/Validation/45662921/confidence"),
        )
        self.assertEqual(
            study.lowres_depth_directory(Path("/confidence"), entry),
            Path("/confidence/raw/Validation/45662921/lowres_depth"),
        )

    def test_held_out_gate_requires_exact_robust_model_and_unchanged_input(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            calibration = output / "calibration"
            calibration.mkdir(parents=True)
            observations = calibration / "observations.jsonl"
            observations.write_text('{"sampleId":"x"}\n')
            gaussian = calibration / study.GAUSSIAN_PREDECESSOR_FILENAME
            gaussian.write_text('{"status":"failed-u1a"}\n')

            split = {"revision": 4}
            split_bytes = b'{"revision":4}'
            robust = calibration / study.ROBUST_MODEL_FILENAME
            payload = {
                "modelId": study.ROBUST_MODEL_ID,
                "status": study.ROBUST_STATUS,
                "splitRevision": 4,
                "splitSha256": hashlib.sha256(split_bytes).hexdigest(),
                "inputSha256": study.sha256_file(observations),
                "likelihood": {
                    "family": "Student-t",
                    "degreesOfFreedom": 3.0,
                    "degreesOfFreedomFitted": False,
                    "sampleFiltering": "none",
                    "sigmaInterpretation": "standard deviation",
                },
                "boundaryFlags": {
                    "depthNoiseFloorAtUpperBound": False,
                    "depthNoiseQuadraticAtUpperBound": False,
                    "sensorConfidencePenaltyAtUpperBound": False,
                },
                "gaussianPredecessor": {"sha256": study.sha256_file(gaussian)},
            }
            robust.write_text(json.dumps(payload))
            path, loaded = study.validate_robust_model(output, split, split_bytes)
            self.assertEqual(path, robust)
            self.assertEqual(loaded["modelId"], study.ROBUST_MODEL_ID)

            observations.write_text('{"sampleId":"changed"}\n')
            with self.assertRaisesRegex(ValueError, "changed after robust model freeze"):
                study.validate_robust_model(output, split, split_bytes)


if __name__ == "__main__":
    unittest.main()
