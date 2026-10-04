from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from aether_proxy.cli import ProxyConfig, ProxyError, atomic_json, parse_colmap_points


class ProxyTests(unittest.TestCase):
    def test_strict_colmap_filtering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "points3D.txt"
            path.write_text(
                "1 0 1 2 255 128 0 0.5 1 0 2 1\n"
                "2 3 4 5 0 255 0 9.0 1 0 2 1\n",
                encoding="utf-8",
            )
            config = ProxyConfig(minimum_points=3)
            with self.assertRaisesRegex(ProxyError, "Only 1 reliable"):
                parse_colmap_points(path, config)

    def test_malformed_track_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "points3D.txt"
            path.write_text("1 0 1 2 255 128 0 0.5 1\n", encoding="utf-8")
            with self.assertRaisesRegex(ProxyError, "Malformed"):
                parse_colmap_points(path, ProxyConfig(minimum_points=3))

    def test_config_rejects_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proxy.json"
            path.write_text('{"schemaVersion":1,"mystery":true}', encoding="utf-8")
            with self.assertRaisesRegex(ProxyError, "Unknown"):
                ProxyConfig.load(path)

    def test_camel_case_config_loads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proxy.json"
            path.write_text('{"schemaVersion":1,"minimumPoints":250,"poissonDepth":8}',
                            encoding="utf-8")
            config = ProxyConfig.load(path)
            self.assertEqual(config.minimum_points, 250)
            self.assertEqual(config.poisson_depth, 8)
            self.assertEqual(config.json_document()["minimumPoints"], 250)

    def test_atomic_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            atomic_json(path, {"schemaVersion": 1, "ok": True})
            self.assertEqual(json.loads(path.read_text())["schemaVersion"], 1)
            self.assertFalse(path.with_name("report.json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
