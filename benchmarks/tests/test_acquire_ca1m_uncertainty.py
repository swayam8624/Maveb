import importlib.util
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "acquire_ca1m_uncertainty.py"
SPEC = importlib.util.spec_from_file_location("acquire_ca1m_uncertainty", MODULE_PATH)
acquire = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(acquire)


class AcquireCa1mUncertaintyTests(unittest.TestCase):
    def payload(self):
        return {
            "schemaVersion": 1,
            "frozen": True,
            "source": {"dataset": "CA-1M / Cubify Anything"},
            "calibrationScenes": ["ca1m-1", "ca1m-2", "ca1m-3"],
            "heldOutScenes": ["ca1m-4", "ca1m-5", "ca1m-6", "ca1m-7", "ca1m-8"],
            "sceneMetadata": {
                f"ca1m-{index}": {
                    "videoId": str(index),
                    "visitId": str(100 + index),
                    "ca1mSplit": "train" if index <= 3 else "val",
                    "role": "calibration" if index <= 3 else "held-out",
                }
                for index in range(1, 9)
            },
        }

    def test_url_index_extracts_video_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.txt"
            path.write_text(
                "https://example/ca1m-train-1.tar\nhttps://example/ca1m-train-2.tar\n"
            )
            self.assertEqual(
                acquire.load_url_index(path),
                {
                    "1": "https://example/ca1m-train-1.tar",
                    "2": "https://example/ca1m-train-2.tar",
                },
            )

    def test_split_requires_membership_and_unique_visits(self):
        payload = self.payload()
        train = {str(index): f"https://x/train-{index}.tar" for index in range(1, 4)}
        val = {str(index): f"https://x/val-{index}.tar" for index in range(4, 9)}
        acquire.validate_split(payload, train, val)
        payload["sceneMetadata"]["ca1m-8"]["visitId"] = "101"
        with self.assertRaisesRegex(ValueError, "visit-level leakage"):
            acquire.validate_split(payload, train, val)

    def test_plan_uses_ca1m_split_filename(self):
        payload = self.payload()
        train = {str(index): f"https://x/ca1m-train-{index}.tar" for index in range(1, 4)}
        val = {str(index): f"https://x/ca1m-val-{index}.tar" for index in range(4, 9)}
        with tempfile.TemporaryDirectory() as directory:
            entries = acquire.plan(payload, train, val, Path(directory))
        self.assertEqual(entries[0]["scene"], "ca1m-1")
        self.assertTrue(entries[0]["destination"].endswith("ca1m-train-1.tar"))
        self.assertTrue(entries[-1]["destination"].endswith("ca1m-val-8.tar"))


if __name__ == "__main__":
    unittest.main()
