#!/usr/bin/env python3

from __future__ import annotations

import csv
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from plan_u6b_confirmatory_acquisition import (  # noqa: E402
    EXPECTED_VIDEOS,
    asset_state,
    load_raw_index,
    validate_frozen_inputs,
)


class U6bAcquisitionPlanTests(unittest.TestCase):
    def test_repository_split_and_protocol_are_bound(self) -> None:
        root = Path(__file__).resolve().parents[2]
        split, protocol = validate_frozen_inputs(
            root / "benchmarks/experiments/metric-uncertainty-u6b-confirmatory-split-v1.json",
            root / "benchmarks/experiments/metric-uncertainty-u6b-opacity-visibility-confirmatory-v1.json",
        )
        split_pairs = [
            (str(item["videoId"]), str(item["visitId"]))
            for item in split["confirmatoryVideos"]
        ]
        self.assertEqual(split_pairs, EXPECTED_VIDEOS)
        protocol_pairs = [
            (str(item["videoId"]), str(item["visitId"]))
            for item in protocol["confirmatorySplit"]["videos"]
        ]
        self.assertEqual(protocol_pairs, EXPECTED_VIDEOS)

    def test_asset_state_is_clean_when_selected_assets_are_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = asset_state(root / "ca1m", root / "arkit", "42898811", "434650")
            self.assertFalse(state["preexisting"])
            self.assertFalse(state["ca1mArchivePresent"])
            self.assertEqual(state["confidencePngCount"], 0)
            self.assertEqual(state["lowresDepthPngCount"], 0)

    def test_asset_state_detects_any_selected_preexisting_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ca1m = root / "ca1m"
            arkit = root / "arkit"
            ca1m.mkdir(parents=True)
            archive = ca1m / "ca1m-val-42898811.tar"
            archive.write_bytes(b"frozen-preexisting-test")
            state = asset_state(ca1m, arkit, "42898811", "434650")
            self.assertTrue(state["preexisting"])
            self.assertTrue(state["ca1mArchivePresent"])
            self.assertIsNotNone(state["ca1mArchiveSha256"])

            archive.unlink()
            confidence = arkit / "raw" / "Validation" / "42898811" / "confidence"
            confidence.mkdir(parents=True)
            (confidence / "1.png").write_bytes(b"x")
            state = asset_state(ca1m, arkit, "42898811", "434650")
            self.assertTrue(state["preexisting"])
            self.assertEqual(state["confidencePngCount"], 1)

    def test_raw_index_preserves_visit_and_fold(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "raw_train_val_splits.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=["video_id", "visit_id", "fold"])
                writer.writeheader()
                writer.writerow({"video_id": "42898811", "visit_id": "434650", "fold": "Validation"})
            index = load_raw_index(path)
            self.assertEqual(index["42898811"], ("434650", "Validation"))


if __name__ == "__main__":
    unittest.main()
