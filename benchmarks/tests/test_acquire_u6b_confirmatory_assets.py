#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from acquire_u6b_confirmatory_assets import (  # noqa: E402
    EXPECTED_METADATA_EVIDENCE_SHA256,
    EXPECTED_PLAN_SHA256,
    EXPECTED_PROTOCOL_SHA256,
    EXPECTED_SPLIT_SHA256,
    EXPECTED_VIDEOS,
    asset_paths,
    ca1m_url,
    extract_sidecar,
    sidecar_url,
    validate_plan_payload,
)


class U6bConfirmatoryAcquisitionTests(unittest.TestCase):
    @staticmethod
    def clean_plan_payload() -> dict:
        return {
            "study": "metric-uncertainty-u6b-opacity-visibility-confirmatory-v1",
            "status": "clean-before-u6b-acquisition",
            "canExecuteAcquisition": True,
            "networkAccessPerformed": False,
            "datasetMutationPerformed": False,
            "preexistingVideoIds": [],
            "splitSha256": EXPECTED_SPLIT_SHA256,
            "protocolSha256": EXPECTED_PROTOCOL_SHA256,
            "publicMetadataEvidenceSha256": EXPECTED_METADATA_EVIDENCE_SHA256,
            "entries": [
                {
                    "videoId": video,
                    "visitId": visit,
                    "preexisting": False,
                }
                for video, visit in EXPECTED_VIDEOS
            ],
        }

    def test_clean_plan_payload_is_accepted(self) -> None:
        validate_plan_payload(self.clean_plan_payload())

    def test_preexisting_selected_asset_is_rejected(self) -> None:
        plan = self.clean_plan_payload()
        plan["entries"][2]["preexisting"] = True
        with self.assertRaises(ValueError):
            validate_plan_payload(plan)

    def test_frozen_urls_are_exact_official_endpoints(self) -> None:
        self.assertEqual(
            ca1m_url("42898811"),
            "https://ml-site.cdn-apple.com/datasets/ca1m/val/ca1m-val-42898811.tar",
        )
        self.assertEqual(
            sidecar_url("42898811", "confidence"),
            "https://docs-assets.developer.apple.com/ml-research/datasets/arkitscenes/v1/raw/Validation/42898811/confidence.zip",
        )
        self.assertEqual(
            sidecar_url("42898811", "lowres_depth"),
            "https://docs-assets.developer.apple.com/ml-research/datasets/arkitscenes/v1/raw/Validation/42898811/lowres_depth.zip",
        )
        with self.assertRaises(ValueError):
            sidecar_url("42898811", "mesh")

    def test_asset_paths_match_existing_dataset_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = asset_paths(root / "CA1M", root / "ARKitScenes", "42898811")
            self.assertEqual(paths["ca1mArchive"].name, "ca1m-val-42898811.tar")
            self.assertEqual(
                paths["confidenceDirectory"],
                root / "ARKitScenes/raw/Validation/42898811/confidence",
            )
            self.assertEqual(
                paths["lowresDepthDirectory"],
                root / "ARKitScenes/raw/Validation/42898811/lowres_depth",
            )

    def test_sidecar_zip_extracts_pngs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            zip_path = root / "confidence.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("confidence/1.png", b"png-test")
                archive.writestr("confidence/2.png", b"png-test-2")
            count = extract_sidecar(zip_path, root, root / "confidence")
            self.assertEqual(count, 2)

    def test_sidecar_zip_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            zip_path = root / "confidence.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("../escape.png", b"bad")
            with self.assertRaises(ValueError):
                extract_sidecar(zip_path, root, root / "confidence")

    def test_repository_plan_evidence_binds_exact_plan(self) -> None:
        root = Path(__file__).resolve().parents[2]
        evidence = json.loads(
            (
                root
                / "benchmarks/evidence/metric-uncertainty-u6b-acquisition-plan-v1.json"
            ).read_text()
        )
        self.assertEqual(evidence["planSha256"], EXPECTED_PLAN_SHA256)
        self.assertTrue(evidence["canExecuteAcquisition"])
        self.assertEqual(evidence["preexistingVideoIds"], [])
        pairs = [
            (str(item["videoId"]), str(item["visitId"]))
            for item in evidence["confirmatoryVideos"]
        ]
        self.assertEqual(pairs, EXPECTED_VIDEOS)


if __name__ == "__main__":
    unittest.main()
