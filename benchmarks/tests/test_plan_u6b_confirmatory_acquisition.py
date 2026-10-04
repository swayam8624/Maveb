#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from plan_u6b_confirmatory_acquisition import (  # noqa: E402
    EXPECTED_ARKIT_METADATA_BLOB_SHA,
    EXPECTED_CA1M_VAL_BLOB_SHA,
    EXPECTED_METADATA_SHA256,
    EXPECTED_VIDEOS,
    asset_state,
    build_plan,
    sha256_file,
    validate_frozen_inputs,
    validate_metadata_evidence,
)


class U6bAcquisitionPlanTests(unittest.TestCase):
    def _repo_paths(self) -> tuple[Path, Path, Path]:
        root = Path(__file__).resolve().parents[2]
        return (
            root / "benchmarks/experiments/metric-uncertainty-u6b-confirmatory-split-v1.json",
            root / "benchmarks/experiments/metric-uncertainty-u6b-opacity-visibility-confirmatory-v1.json",
            root / "benchmarks/evidence/metric-uncertainty-u6b-public-metadata-v1.json",
        )

    def test_repository_split_protocol_and_metadata_are_bound(self) -> None:
        split_path, protocol_path, metadata_path = self._repo_paths()
        split, protocol, metadata = validate_frozen_inputs(
            split_path, protocol_path, metadata_path
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
        metadata_pairs = [
            (str(item["videoId"]), str(item["visitId"]))
            for item in metadata["selectedValidationRows"]
        ]
        self.assertEqual(metadata_pairs, EXPECTED_VIDEOS)
        self.assertEqual(sha256_file(metadata_path), EXPECTED_METADATA_SHA256)

    def test_metadata_evidence_binds_upstream_blob_identities(self) -> None:
        _, _, metadata_path = self._repo_paths()
        metadata = validate_metadata_evidence(metadata_path)
        self.assertEqual(
            metadata["publicSources"]["arkitScenesRawSplit"]["gitBlobSha"],
            EXPECTED_ARKIT_METADATA_BLOB_SHA,
        )
        self.assertEqual(
            metadata["publicSources"]["ca1mValidationList"]["gitBlobSha"],
            EXPECTED_CA1M_VAL_BLOB_SHA,
        )

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

    def test_build_plan_does_not_require_local_metadata_csv(self) -> None:
        split_path, protocol_path, metadata_path = self._repo_paths()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = build_plan(
                split_path=split_path,
                protocol_path=protocol_path,
                metadata_path=metadata_path,
                ca1m_root=root / "ca1m",
                arkit_root=root / "arkit",
            )
            self.assertTrue(plan["canExecuteAcquisition"])
            self.assertFalse(plan["localArkitMetadataCsvRequired"])
            self.assertEqual(plan["preexistingVideoIds"], [])
            self.assertEqual(len(plan["entries"]), 5)


if __name__ == "__main__":
    unittest.main()
