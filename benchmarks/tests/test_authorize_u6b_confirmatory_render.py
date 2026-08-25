#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "authorize_u6b_confirmatory_render.py"
spec = importlib.util.spec_from_file_location("authorize_u6b_confirmatory_render", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class U6bRenderAuthorizationTests(unittest.TestCase):
    def minimal_preparation(self) -> dict:
        scenes = []
        for scene in module.EXPECTED_SCENES:
            scenes.append(
                {
                    "scene": scene,
                    "methods": {
                        method: {
                            "gaussianPath": "/tmp/not-used.ply",
                            "gaussianSha256": "sha",
                            "primitiveCount": 10,
                        }
                        for method in module.METHODS
                    },
                    "primitiveCount": 10,
                }
            )
        return {
            "study": module.STUDY_ID,
            "status": "prepared-no-u6b-render-or-metric-outcomes",
            "protocolSha256": module.PROTOCOL_SHA256,
            "acquisitionLedgerSha256": module.ACQUISITION_SHA256,
            "acquisitionEvidenceSha256": "e" * 64,
            "acquisitionEvidenceStage": module.ACQUISITION_EVIDENCE_STAGE,
            "noRenderedDepthProduced": True,
            "noU6bMetricsProduced": True,
            "methods": list(module.METHODS),
            "scenes": scenes,
        }

    def test_frozen_authorization_counts(self) -> None:
        self.assertEqual(len(module.EXPECTED_SCENES), 5)
        self.assertEqual(len(module.METHODS), 3)
        self.assertEqual(5 * 3 * 8, 120)

    def test_preparation_requires_unopened_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preparation.json"
            payload = self.minimal_preparation()
            path.write_text(json.dumps(payload))
            loaded = module.validate_preparation(path)
            self.assertTrue(loaded["noRenderedDepthProduced"])

            payload["noRenderedDepthProduced"] = False
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "crossed the outcome boundary"):
                module.validate_preparation(path)

    def test_preparation_requires_exact_method_and_scene_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preparation.json"
            payload = self.minimal_preparation()
            payload["methods"] = list(reversed(module.METHODS))
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "method order changed"):
                module.validate_preparation(path)

            payload = self.minimal_preparation()
            payload["scenes"] = list(reversed(payload["scenes"]))
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "scene order changed"):
                module.validate_preparation(path)

    def test_preparation_requires_original_acquisition_ledger_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preparation.json"
            payload = self.minimal_preparation()
            payload["acquisitionLedgerSha256"] = "wrong"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "acquisition-ledger SHA mismatch"):
                module.validate_preparation(path)

    def test_preparation_requires_public_acquisition_evidence_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preparation.json"
            payload = self.minimal_preparation()
            del payload["acquisitionEvidenceSha256"]
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "acquisition-evidence SHA"):
                module.validate_preparation(path)

            payload = self.minimal_preparation()
            payload["acquisitionEvidenceStage"] = "wrong-stage"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "acquisition-evidence stage mismatch"):
                module.validate_preparation(path)


if __name__ == "__main__":
    unittest.main()
