from __future__ import annotations

import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/cbrc_prepare_real_campaign.py"
spec = importlib.util.spec_from_file_location("cbrc_prepare_real_campaign", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def make_world(root: Path, *, count: int = 20) -> Path:
    archive = root / "real-scene.aetherworld"
    archive.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "nextEntityId": 3,
                "snapshots": [
                    {
                        "revision": 1,
                        "timestamp": 100,
                        "entities": [
                            {
                                "id": 1,
                                "name": "object-a",
                                "semanticLabel": "object",
                                "translation": [0.0, 0.0, 0.0],
                            },
                            {
                                "id": 2,
                                "name": "object-b",
                                "semanticLabel": "object",
                                "translation": [1.0, 0.0, 0.0],
                            },
                        ],
                    }
                ],
            }
        )
    )

    gaussian = bytearray(32 + count * 256)
    gaussian[:8] = b"AETHGS\x00\x00"
    struct.pack_into("<H", gaussian, 8, 1)
    struct.pack_into("<H", gaussian, 10, 0)
    struct.pack_into("<I", gaussian, 12, 256)
    struct.pack_into("<Q", gaussian, 16, count)
    struct.pack_into("<I", gaussian, 24, 0)
    struct.pack_into("<I", gaussian, 28, 0)
    for index in range(count):
        struct.pack_into(
            "<3f",
            gaussian,
            32 + index * 256,
            float(index % 5) * 0.1,
            float((index // 5) % 4) * 0.1,
            1.0 + 0.01 * index,
        )
    Path(str(archive) + ".gaussians.r1.bin").write_bytes(gaussian)

    ownership = bytearray(32 + count * 8)
    ownership[:8] = b"MVGOWNR\x00"
    struct.pack_into("<I", ownership, 8, 1)
    struct.pack_into("<I", ownership, 12, 32)
    struct.pack_into("<Q", ownership, 16, count)
    struct.pack_into("<Q", ownership, 24, 0)
    for index in range(count):
        struct.pack_into("<Q", ownership, 32 + index * 8, 1 if index < 5 else 2)
    Path(str(archive) + ".ownership.r1.bin").write_bytes(ownership)
    return archive


class CBRCPrepareRealCampaignTests(unittest.TestCase):
    def test_inspects_and_freezes_independent_real_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = make_world(root)
            candidate = mod.inspect_archive(archive)
            self.assertEqual(candidate.gaussian_count, 20)
            self.assertEqual(candidate.revision, 1)

            out = root / "freeze"
            campaign, provenance = mod.build_campaign(
                [candidate],
                out,
                1.0 / 255.0,
                None,
            )
            self.assertEqual(len(campaign["cases"]), 5)
            self.assertTrue(campaign["require_full_fallback"])
            self.assertFalse(
                campaign["cases"][-1]["revision"]["history_stable"]
            )
            self.assertEqual(
                len(campaign["cases"][0]["revision"]["camera"]["world_to_camera"]),
                16,
            )
            archives = [
                Path(case["revision"]["archive"])
                for case in campaign["cases"]
            ]
            self.assertEqual(len(set(archives)), 5)
            self.assertTrue(all(path.is_file() for path in archives))
            self.assertEqual(len(provenance["frozen_inputs"]), 5)

    def test_missing_sidecar_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = make_world(root)
            Path(str(archive) + ".ownership.r1.bin").unlink()
            with self.assertRaises(FileNotFoundError):
                mod.inspect_archive(archive)


if __name__ == "__main__":
    unittest.main()
