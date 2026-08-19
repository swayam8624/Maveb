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
            count = study.annotate_method(source, output, "u1-intact-confidence")
            self.assertEqual(count, 1)
            row = json.loads(output.read_text())
            self.assertEqual(row["scene"], "s")
            self.assertEqual(row["method"], "u1-intact-confidence")

    def test_load_split_rejects_unfrozen_or_leaky_split(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "split.json"
            path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "frozen": False,
                        "calibrationScenes": ["a", "b", "c"],
                        "heldOutScenes": ["d", "e", "f", "g", "h"],
                        "sceneMetadata": {},
                    }
                )
            )
            with self.assertRaisesRegex(ValueError, "frozen"):
                study.load_split(path)

            path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "frozen": True,
                        "calibrationScenes": ["a", "b", "c"],
                        "heldOutScenes": ["c", "e", "f", "g", "h"],
                        "sceneMetadata": {},
                    }
                )
            )
            with self.assertRaisesRegex(ValueError, "isolation"):
                study.load_split(path)


if __name__ == "__main__":
    unittest.main()
