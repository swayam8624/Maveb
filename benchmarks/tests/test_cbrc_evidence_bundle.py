from __future__ import annotations

import importlib.util
import hashlib
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/cbrc_evidence_bundle.py"
spec = importlib.util.spec_from_file_location("cbrc_evidence_bundle", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class CBRCEvidenceBundleTests(unittest.TestCase):
    def test_sha256_is_content_addressed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x"
            path.write_bytes(b"abc")
            self.assertEqual(
                mod.sha256(path),
                hashlib.sha256(b"abc").hexdigest(),
            )

    def test_native_planner_certificate_matches_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "native.json"
            path.write_text(
                """{
  "schemaVersion": 1,
  "artifact": "maveb-cbrc-native-certificate",
  "graphVersion": "gaussian-output-cone-v2",
  "boundVersion": "gaussian-image-temporal-v1",
  "costModelVersion": "temporal-pixel-work-v1",
  "stable": true,
  "passes": true,
  "fullRebuild": false,
  "work": 25.0,
  "fullWork": 100.0,
  "qois": [
    {
      "name": "resolved-rgb-linf",
      "bound": 0.02,
      "epsilon": 0.03,
      "passes": true
    }
  ]
}
"""
            )
            manifest = {
                "graph_scope": "gaussian-output-cone-v2",
                "bound_version": "gaussian-image-temporal-v1",
                "production_certificate": {
                    "outputConePlanner": {
                        "stable": True,
                        "passes": True,
                        "fullRepair": False,
                        "plannerWork": 25.0,
                        "fullWork": 100.0,
                        "resolvedRgbBound": 0.02,
                        "epsilon": 0.03,
                    }
                },
            }
            payload = mod.validate_native_planner_certificate(path, manifest)
            self.assertEqual(payload["work"], 25.0)

    def test_native_planner_certificate_version_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "native.json"
            path.write_text(
                """{
  "schemaVersion": 1,
  "artifact": "maveb-cbrc-native-certificate",
  "graphVersion": "stale-graph",
  "boundVersion": "gaussian-image-temporal-v1",
  "costModelVersion": "temporal-pixel-work-v1",
  "stable": true,
  "passes": true,
  "fullRebuild": false,
  "work": 25.0,
  "fullWork": 100.0,
  "qois": [
    {
      "name": "resolved-rgb-linf",
      "bound": 0.02,
      "epsilon": 0.03,
      "passes": true
    }
  ]
}
"""
            )
            manifest = {
                "graph_scope": "gaussian-output-cone-v2",
                "bound_version": "gaussian-image-temporal-v1",
                "production_certificate": {
                    "outputConePlanner": {
                        "stable": True,
                        "passes": True,
                        "fullRepair": False,
                        "plannerWork": 25.0,
                        "fullWork": 100.0,
                        "resolvedRgbBound": 0.02,
                        "epsilon": 0.03,
                    }
                },
            }
            with self.assertRaisesRegex(ValueError, "graphVersion"):
                mod.validate_native_planner_certificate(path, manifest)

    def test_negative_epsilon_fails_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = []
            for name in ("translation.json", "certificate.json", "oracle"):
                path = root / name
                path.write_text("{}")
                files.append(path)
            with self.assertRaisesRegex(ValueError, "epsilon"):
                mod.bundle(
                    translation=files[0],
                    certificate=files[1],
                    oracle=files[2],
                    scene_id="scene",
                    git_sha="abc",
                    epsilon=-1,
                    output_dir=root / "out",
                )


if __name__ == "__main__":
    unittest.main()
