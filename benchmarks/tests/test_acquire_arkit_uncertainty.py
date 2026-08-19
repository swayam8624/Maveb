import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "acquire_arkit_uncertainty.py"
SPEC = importlib.util.spec_from_file_location("acquire_arkit_uncertainty", MODULE_PATH)
acquire = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(acquire)


class AcquireArkitUncertaintyTests(unittest.TestCase):
    def frozen_split(self):
        return {
            "schemaVersion": 1,
            "frozen": True,
            "rules": {"minimumCalibrationScenes": 3, "minimumHeldOutScenes": 5},
            "calibrationScenes": ["arkitscenes-1", "arkitscenes-2", "arkitscenes-3"],
            "heldOutScenes": [
                "arkitscenes-4",
                "arkitscenes-5",
                "arkitscenes-6",
                "arkitscenes-7",
                "arkitscenes-8",
            ],
            "sceneMetadata": {
                f"arkitscenes-{index}": {
                    "videoId": str(index),
                    "visitId": str(100 + index),
                    "fold": "Training" if index <= 3 else "Validation",
                    "role": "calibration" if index <= 3 else "held-out",
                }
                for index in range(1, 9)
            },
        }

    def test_split_rejects_visit_level_leakage(self):
        payload = self.frozen_split()
        payload["sceneMetadata"]["arkitscenes-8"]["visitId"] = "101"
        with self.assertRaisesRegex(ValueError, "visit-level leakage"):
            acquire.validate_split(payload)

    def test_official_split_must_match_frozen_metadata(self):
        payload = self.frozen_split()
        acquire.validate_split(payload)
        official = {
            str(index): (
                str(100 + index),
                "Training" if index <= 3 else "Validation",
            )
            for index in range(1, 9)
        }
        acquire.validate_against_official_split(payload, official)
        official["4"] = ("999", "Validation")
        with self.assertRaisesRegex(ValueError, "official split mismatch"):
            acquire.validate_against_official_split(payload, official)

    def test_download_plan_groups_by_official_fold_and_requests_only_required_assets(self):
        payload = self.frozen_split()
        acquire.validate_split(payload)
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "ARKitScenes"
            data = Path(directory) / "data"
            commands = acquire.download_commands(payload, arkit_repo=repo, download_dir=data)
        self.assertEqual(len(commands), 2)
        training, validation = commands
        self.assertIn("Training", training)
        self.assertIn("Validation", validation)
        self.assertEqual(
            training[training.index("--video_id") + 1 : training.index("--download_dir")],
            ["1", "2", "3"],
        )
        self.assertEqual(
            validation[validation.index("--video_id") + 1 : validation.index("--download_dir")],
            ["4", "5", "6", "7", "8"],
        )
        asset_index = training.index("--raw_dataset_assets") + 1
        self.assertEqual(tuple(training[asset_index:]), acquire.REQUIRED_RAW_ASSETS)

    def test_expected_download_layout_matches_official_downloader(self):
        entry = {"fold": "Validation", "videoId": "41069021"}
        root = acquire.expected_scene_root(Path("/tmp/arkit"), entry)
        self.assertEqual(root, Path("/tmp/arkit/raw/Validation/41069021"))


if __name__ == "__main__":
    unittest.main()
