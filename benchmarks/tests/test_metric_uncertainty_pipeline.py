import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "benchmarks" / "scripts"
FIXTURE = ROOT / "benchmarks" / "fixtures" / "metric-uncertainty-synthetic.jsonl"


class MetricUncertaintyPipelineTests(unittest.TestCase):
    def test_observation_prediction_calibration_cli_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            predictions = root / "predictions.jsonl"
            report = root / "calibration.json"
            markdown = root / "calibration.md"

            predictor = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "geometric_uncertainty.py"),
                    str(FIXTURE),
                    "--output",
                    str(predictions),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(predictor.returncode, 0, predictor.stderr)
            prediction_rows = [
                json.loads(line) for line in predictions.read_text().splitlines() if line.strip()
            ]
            self.assertEqual(len(prediction_rows), 8)
            self.assertTrue(all(row["predictedSigmaMetres"] > 0.0 for row in prediction_rows))
            self.assertTrue(all("signedErrorMetres" in row for row in prediction_rows))

            evaluator = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "uncertainty_metrics.py"),
                    str(predictions),
                    "--output",
                    str(report),
                    "--markdown",
                    str(markdown),
                    "--bins",
                    "2",
                    "--bootstrap",
                    "16",
                    "--bootstrap-seed",
                    "7",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(evaluator.returncode, 0, evaluator.stderr)
            payload = json.loads(report.read_text())
            self.assertEqual(payload["schemaVersion"], 1)
            self.assertEqual(payload["bootstrapReplicates"], 16)
            self.assertEqual(len(payload["groups"]), 2)
            self.assertEqual(
                payload["inputSha256"], hashlib.sha256(predictions.read_bytes()).hexdigest()
            )
            scenes = {record["group"]["scene"] for record in payload["groups"]}
            self.assertEqual(scenes, {"synthetic-near", "synthetic-far"})
            self.assertIn("Metric uncertainty calibration", markdown.read_text())


if __name__ == "__main__":
    unittest.main()
