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


class U6bFrozenAcquisitionPreparationBridgeTests(unittest.TestCase):
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

    def test_preparation_is_rebound_to_original_ledger_and_keeps_evidence_sha(self) -> None:
        evidence = self.evidence()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence_path = root / "acquisition-evidence.json"
            evidence_path.write_text(json.dumps(evidence, sort_keys=True) + "\n")
            evidence_sha = MODULE.base.sha256_file(evidence_path)
            preparation_path = root / "preparation.json"
            preparation_path.write_text(
                json.dumps(
                    {
                        "study": MODULE.base.STUDY_ID,
                        "status": "prepared-no-u6b-render-or-metric-outcomes",
                        "acquisitionLedgerSha256": evidence_sha,
                        "noRenderedDepthProduced": True,
                        "noU6bMetricsProduced": True,
                    }
                )
            )
            MODULE.finalize_preparation_provenance(
                preparation_path,
                acquisition_evidence_path=evidence_path,
                acquisition_evidence=evidence,
            )
            prepared = json.loads(preparation_path.read_text())
            self.assertEqual(
                prepared["acquisitionLedgerSha256"],
                MODULE.base.ACQUISITION_SHA256,
            )
            self.assertEqual(prepared["acquisitionEvidenceSha256"], evidence_sha)
            self.assertTrue(prepared["noRenderedDepthProduced"])
            self.assertTrue(prepared["noU6bMetricsProduced"])


if __name__ == "__main__":
    unittest.main()
