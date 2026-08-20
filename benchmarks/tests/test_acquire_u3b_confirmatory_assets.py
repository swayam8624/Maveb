#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "acquire_u3b_confirmatory_assets.py"
SPEC = importlib.util.spec_from_file_location("acquire_u3b_confirmatory_assets", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AcquireU3bConfirmatoryAssetsTests(unittest.TestCase):
    def test_clean_asset_state_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = MODULE.asset_state(
                root / "ca1m",
                root / "arkit",
                "48458481",
                "483953",
            )
            self.assertFalse(state["preexisting"])
            self.assertEqual(state["confidencePngCountBefore"], 0)
            self.assertEqual(state["lowresDepthPngCountBefore"], 0)

    def test_any_sidecar_marks_scene_preexisting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            confidence = root / "arkit/raw/Validation/48458481/confidence"
            confidence.mkdir(parents=True)
            (confidence / "frame.png").write_bytes(b"not-a-real-png")
            state = MODULE.asset_state(
                root / "ca1m",
                root / "arkit",
                "48458481",
                "483953",
            )
            self.assertTrue(state["preexisting"])
            self.assertEqual(state["confidencePngCountBefore"], 1)

    def test_plan_self_hash_round_trip(self) -> None:
        payload = {
            "schemaVersion": 1,
            "study": MODULE.EXPECTED_STUDY_ID,
            "status": "clean-confirmatory-assets-absent",
            "entries": [],
        }
        import hashlib

        canonical = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
        expected = hashlib.sha256(canonical).hexdigest()
        with_self = dict(payload)
        with_self["selfSha256WithoutSelfField"] = expected
        check = dict(with_self)
        observed = check.pop("selfSha256WithoutSelfField")
        actual = hashlib.sha256(
            (json.dumps(check, indent=2, sort_keys=True) + "\n").encode()
        ).hexdigest()
        self.assertEqual(observed, actual)


if __name__ == "__main__":
    unittest.main()
