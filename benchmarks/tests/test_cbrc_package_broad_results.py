from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/cbrc_package_broad_results.py"
SPEC = importlib.util.spec_from_file_location("cbrc_package_broad_results", MODULE_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(mod)


class BroadResultPackagerTests(unittest.TestCase):
    def test_absolute_paths_are_redacted(self):
        self.assertEqual(mod.safe_string("/Users/example/data/scene.ply"), "$LOCAL_PATH/scene.ply")
        self.assertEqual(mod.safe_string("https://example.org/data"), "https://example.org/data")

    def test_recursive_sanitization(self):
        value = {"a": ["/tmp/foo.json", {"url": "https://x.test/y"}]}
        self.assertEqual(
            mod.sanitize(value),
            {"a": ["$LOCAL_PATH/foo.json", {"url": "https://x.test/y"}]},
        )


if __name__ == "__main__":
    unittest.main()
