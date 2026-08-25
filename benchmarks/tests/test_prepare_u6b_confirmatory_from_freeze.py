#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "benchmarks" / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "prepare_u6b_confirmatory_from_freeze",
    SCRIPTS / "prepare_u6b_confirmatory_from_freeze.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class U6bFrozenPreparationBridgeTests(unittest.TestCase):
    def evidence(self) -> dict:
        return {
            "schemaVersion": 1,
            "study": MODULE.base.STUDY_ID,
            "stage": MODULE.ACQUISITION_FREEZE_STAGE,
            "status": "acquired-after-frozen-clean-plan",
            "protocolSha256": MODULE.base.PROTOCOL_SHA256,
            "acquisitionLedgerSha256": MODULE.base.ACQUISITION_SHA256,
            "selectedAssetsAbsentAtFrozenPlan": True,
            "partialFilesRemaining": 0,
            "u6bRenderedDepthCountAfterAcquisition": 0,
            "entries": [
                {
                    "videoId": video,
                    "visitId": str(index),
                    "ca1mArchiveSha256": "",
                    "ca1mArchiveBytes": 0,
                    "confidenceZipSha256": "",
                    "confidencePngCount": 1,
                    "lowresDepthZipSha256": "",
                    "lowresDepthPngCount": 1,
                }
                for index, video in enumerate(MODULE.base.EXPECTED_VIDEOS)
            ],
        }

    def preflight_evidence(self) -> dict:
        return {
            "schemaVersion": 1,
            "study": MODULE.base.STUDY_ID,
            "stage": MODULE.PREFLIGHT_FREEZE_STAGE,
            "status": "passed",
            "protocolSha256": MODULE.base.PROTOCOL_SHA256,
            "acquisitionLedgerSha256": MODULE.base.ACQUISITION_SHA256,
            "inputPreflightSha256": MODULE.base.PREFLIGHT_SHA256,
            "inputPreflightLogSha256": MODULE.base.PREFLIGHT_SHA256,
            "allScenesPassed": True,
            "noRepresentationOutcomeProduced": True,
            "u6bPlyCountAfterPreflight": 0,
            "u6bRenderedDepthCountAfterPreflight": 0,
            "scenes": [
                {
                    "videoId": video,
                    "visitId": str(index),
                    "completeFrames": 100,
                    "posePassed": True,
                    "cameraToWorldSupportedPairCount": 16,
                    "inverseSupportedPairCount": 2,
                    "mutuallyComparablePairCount": 2,
                    "cameraToWorldWinsAmongComparable": 2,
                    "cameraToWorldMedianOfSupportedPairMediansMetres": 0.001,
                    "inverseMedianOfSupportedPairMediansMetres": 0.3,
                    "orientationPassed": True,
                    "acceptedSourceCount": 8,
                    "maximumBestOrientationMedianAbsErrorMillimetres": 10.0,
                    "dominantAcceptedTransform": "identity",
                }
                for index, video in enumerate(MODULE.base.EXPECTED_VIDEOS)
            ],
        }

    def runtime_scene(self, *, video: str | None = None, visit: str = "0") -> dict:
        video = video or MODULE.base.EXPECTED_VIDEOS[0]
        sources = [
            {
                "sourceIndex": index,
                "sidecarMatched": True,
                "orientationAccepted": True,
                "confidenceLevelsAndShapeValid": True,
                "bestOrientation": {
                    "transform": "identity",
                    "medianAbsErrorMillimetres": 10.0,
                },
            }
            for index in range(8)
        ]
        return {
            "videoId": video,
            "visitId": visit,
            "completeFrames": 100,
            "poseConventionValidation": {
                "passed": True,
                "cameraToWorldSupportedPairCount": 16,
                "inverseSupportedPairCount": 2,
                "mutuallyComparablePairCount": 2,
                "cameraToWorldWinsAmongComparable": 2,
                "cameraToWorldMedianOfSupportedPairMediansMetres": 0.001,
                "inverseMedianOfSupportedPairMediansMetres": 0.3,
            },
            "primaryEightViewSelection": sources,
            "orientationPreflightPassed": True,
            "scenePassed": True,
        }

    def test_frozen_evidence_binds_original_runtime_ledger(self) -> None:
        payload = self.evidence()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "acquisition.json"
            path.write_text(json.dumps(payload))
            loaded = MODULE.validate_acquisition_evidence(path)
            self.assertEqual(
                loaded["acquisitionLedgerSha256"],
                MODULE.base.ACQUISITION_SHA256,
            )

            payload["acquisitionLedgerSha256"] = "wrong"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "runtime ledger"):
                MODULE.validate_acquisition_evidence(path)

    def test_frozen_preflight_evidence_binds_original_runtime_preflight(self) -> None:
        payload = self.preflight_evidence()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preflight.json"
            path.write_text(json.dumps(payload))
            loaded = MODULE.validate_preflight_evidence(path)
            self.assertEqual(loaded["inputPreflightSha256"], MODULE.base.PREFLIGHT_SHA256)

            payload["inputPreflightSha256"] = "wrong"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "runtime preflight"):
                MODULE.validate_preflight_evidence(path)

    def test_local_assets_are_resolved_and_hash_verified(self) -> None:
        payload = self.evidence()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ca1m_root = root / "ca1m"
            arkit_root = root / "arkit"
            ca1m_root.mkdir()
            for item in payload["entries"]:
                video = item["videoId"]
                archive = ca1m_root / f"ca1m-val-{video}.tar"
                archive.write_bytes(f"archive-{video}".encode())
                raw_root = arkit_root / "raw" / "Validation" / video
                confidence_zip = raw_root / "confidence.zip"
                lowres_zip = raw_root / "lowres_depth.zip"
                confidence_dir = raw_root / "confidence"
                lowres_dir = raw_root / "lowres_depth"
                confidence_dir.mkdir(parents=True)
                lowres_dir.mkdir(parents=True)
                confidence_zip.write_bytes(f"confidence-{video}".encode())
                lowres_zip.write_bytes(f"lowres-{video}".encode())
                (confidence_dir / "frame.png").write_bytes(b"png")
                (lowres_dir / "frame.png").write_bytes(b"png")
                item["ca1mArchiveSha256"] = MODULE.base.sha256_file(archive)
                item["ca1mArchiveBytes"] = archive.stat().st_size
                item["confidenceZipSha256"] = MODULE.base.sha256_file(confidence_zip)
                item["lowresDepthZipSha256"] = MODULE.base.sha256_file(lowres_zip)

            runtime = MODULE.resolve_runtime_acquisition(
                payload,
                ca1m_root=ca1m_root,
                arkit_root=arkit_root,
            )
            self.assertEqual(
                [entry["videoId"] for entry in runtime["entries"]],
                MODULE.base.EXPECTED_VIDEOS,
            )
            self.assertEqual(
                runtime["acquisitionLedgerSha256"],
                MODULE.base.ACQUISITION_SHA256,
            )
            self.assertTrue(Path(runtime["entries"][0]["ca1mArchive"]).is_file())

    def test_reconstructed_scene_must_match_frozen_summary(self) -> None:
        runtime = self.runtime_scene()
        frozen = self.preflight_evidence()["scenes"][0]
        MODULE.verify_reconstructed_scene(runtime, frozen)

        frozen["maximumBestOrientationMedianAbsErrorMillimetres"] = 11.0
        with self.assertRaisesRegex(ValueError, "maximum orientation median"):
            MODULE.verify_reconstructed_scene(runtime, frozen)

    def test_preparation_rebinds_both_original_runtime_artifacts(self) -> None:
        acquisition = self.evidence()
        preflight_evidence = self.preflight_evidence()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            acquisition_path = root / "acquisition-evidence.json"
            acquisition_path.write_text(json.dumps(acquisition, sort_keys=True) + "\n")
            acquisition_sha = MODULE.base.sha256_file(acquisition_path)
            preflight_path = root / "preflight-evidence.json"
            preflight_path.write_text(json.dumps(preflight_evidence, sort_keys=True) + "\n")
            preflight_sha = MODULE.base.sha256_file(preflight_path)
            preparation_path = root / "preparation.json"
            preparation_path.write_text(
                json.dumps(
                    {
                        "study": MODULE.base.STUDY_ID,
                        "status": "prepared-no-u6b-render-or-metric-outcomes",
                        "acquisitionLedgerSha256": acquisition_sha,
                        "inputPreflightSha256": preflight_sha,
                        "noRenderedDepthProduced": True,
                        "noU6bMetricsProduced": True,
                    }
                )
            )
            MODULE.finalize_preparation_provenance(
                preparation_path,
                acquisition_evidence_path=acquisition_path,
                acquisition_evidence=acquisition,
                preflight_evidence_path=preflight_path,
                preflight_evidence=preflight_evidence,
            )
            prepared = json.loads(preparation_path.read_text())
            self.assertEqual(
                prepared["acquisitionLedgerSha256"], MODULE.base.ACQUISITION_SHA256
            )
            self.assertEqual(prepared["acquisitionEvidenceSha256"], acquisition_sha)
            self.assertEqual(prepared["inputPreflightSha256"], MODULE.base.PREFLIGHT_SHA256)
            self.assertEqual(prepared["inputPreflightEvidenceSha256"], preflight_sha)
            self.assertTrue(prepared["noRenderedDepthProduced"])
            self.assertTrue(prepared["noU6bMetricsProduced"])


if __name__ == "__main__":
    unittest.main()
