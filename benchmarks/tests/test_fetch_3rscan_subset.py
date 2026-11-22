from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "scripts/fetch_3rscan_subset.py"
SPEC = importlib.util.spec_from_file_location("fetch_3rscan_subset", MODULE)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(mod)


class Fetch3RScanSubsetTests(unittest.TestCase):
    def test_changed_pairs_match_importer_sort_rule(self):
        metadata = [
            {
                "reference": "ref-b",
                "type": "validation",
                "scans": [
                    {"reference": "rescan-b", "rigid": [{}, {}], "removed": [], "nonrigid": []}
                ],
            },
            {
                "reference": "ref-a",
                "type": "val",
                "scans": [
                    {"reference": "rescan-a2", "rigid": [{}], "removed": [{}], "nonrigid": [{}]},
                    {"reference": "rescan-a1", "rigid": [{}], "removed": [], "nonrigid": []},
                ],
            },
            {
                "reference": "train-ref",
                "type": "train",
                "scans": [{"reference": "train-rescan", "rigid": [{}, {}, {}, {}]}],
            },
        ]
        result = mod.changed_pairs(metadata, 2)
        self.assertEqual(
            [item["pairId"] for item in result],
            ["ref-a__rescan-a2", "ref-b__rescan-b"],
        )
        self.assertEqual([item["changeCount"] for item in result], [3, 2])


if __name__ == "__main__":
    unittest.main()
