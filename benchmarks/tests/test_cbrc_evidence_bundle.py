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
