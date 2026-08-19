import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "acquire_arkitscenes_confidence.py"
SPEC = importlib.util.spec_from_file_location("acquire_arkitscenes_confidence", MODULE_PATH)
acquire = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(acquire)


class AcquireArkitScenesConfidenceTests(unittest.TestCase):
    def test_plan_validates_fold_and_visit(self):
        payload = {
            "calibrationScenes": ["ca1m-1"],
            "heldOutScenes": ["ca1m-2"],
            "sceneMetadata": {
                "ca1m-1": {
                    "videoId": "1",
                    "visitId": "10",
                    "arkitFold": "Training",
                    "role": "calibration",
                },
                "ca1m-2": {
                    "videoId": "2",
                    "visitId": "20",
                    "arkitFold": "Validation",
                    "role": "held-out",
                },
            },
        }
        index = {"1": ("10", "Training"), "2": ("20", "Validation")}
        planned = acquire.plan(payload, index, Path("/tmp/data"), "calibration")
        self.assertEqual(len(planned), 1)
        self.assertEqual(planned[0]["videoId"], "1")
        self.assertTrue(planned[0]["confidenceDirectory"].endswith("raw/Training/1/confidence"))

        bad_index = {"1": ("999", "Training"), "2": ("20", "Validation")}
        with self.assertRaisesRegex(ValueError, "metadata mismatch"):
            acquire.plan(payload, bad_index, Path("/tmp/data"), "calibration")

    def test_load_raw_index_uses_standard_library_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "split.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=["video_id", "visit_id", "fold"])
                writer.writeheader()
                writer.writerow({"video_id": "1", "visit_id": "10", "fold": "Training"})
            self.assertEqual(acquire.load_raw_index(path), {"1": ("10", "Training")})

    def test_load_split_requires_confidence_sidecar_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "split.json"
            path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "frozen": True,
                        "source": {
                            "dataset": "CA-1M / Cubify Anything",
                            "confidenceDataset": "ARKitScenes raw",
                        },
                    }
                )
            )
            payload, _ = acquire.load_split(path)
            self.assertEqual(payload["source"]["confidenceDataset"], "ARKitScenes raw")


if __name__ == "__main__":
    unittest.main()
