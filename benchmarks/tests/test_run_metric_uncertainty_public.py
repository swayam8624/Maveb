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

    def test_load_split_requires_frozen_ca1m_source_and_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "split.json"
            payload = {
                "schemaVersion": 1,
                "frozen": True,
                "source": {"dataset": "CA-1M / Cubify Anything"},
                "calibrationScenes": ["a", "b", "c"],
                "heldOutScenes": ["d", "e", "f", "g", "h"],
                "sceneMetadata": {},
            }
            path.write_text(json.dumps(payload))
            loaded, _ = study.load_split(path)
            self.assertEqual(loaded["source"]["dataset"], "CA-1M / Cubify Anything")

            payload["heldOutScenes"][0] = "c"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "isolation"):
                study.load_split(path)

            payload["heldOutScenes"][0] = "d"
            payload["source"]["dataset"] = "ARKitScenes raw"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "CA-1M"):
                study.load_split(path)

    def test_archive_path_uses_ca1m_split_and_video_id(self):
        entry = {"ca1mSplit": "val", "videoId": "45662921"}
        self.assertEqual(
            study.archive_path(Path("/data"), entry),
            Path("/data/ca1m-val-45662921.tar"),
        )


if __name__ == "__main__":
    unittest.main()
