from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "benchmarks/scripts/cbrc_migrate_broad_gate_policy.py"
spec = importlib.util.spec_from_file_location("cbrc_migrate_broad_gate_policy", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)


class BroadGateMigrationTests(unittest.TestCase):
    def test_policy_changes_without_changing_cases(self):
        campaign = {
            "schemaVersion": 4,
            "campaignId": "maveb-cbrc-broad-benchmark-v1",
            "require_full_fallback": True,
            "require_high_coupling": True,
            "cases": [
                {"id": "a", "coupling_regime": "low", "epsilon": 0.1},
                {"id": "b", "coupling_regime": "low", "epsilon": 0.2},
                {"id": "c", "coupling_regime": "low", "epsilon": 0.3},
            ],
        }
        before = mod.canonical_cases_sha256(campaign)
        desired = mod.policy(campaign)

        migrated = dict(campaign)
        migrated["require_full_fallback"] = desired["require_full_fallback"]
        migrated["require_high_coupling"] = desired["require_high_coupling"]
        migrated["broad_gate_policy"] = desired["metadata"]

        self.assertEqual(before, mod.canonical_cases_sha256(migrated))
        self.assertFalse(migrated["require_full_fallback"])
        self.assertFalse(migrated["require_high_coupling"])
        self.assertEqual(
            migrated["broad_gate_policy"]["frozenCouplingRegimes"],
            ["low"],
        )

    def test_write_preserves_json_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "value.json"
            payload = {"cases": [{"id": "x"}], "value": 1}
            mod.write(path, payload)
            self.assertEqual(json.loads(path.read_text()), payload)


if __name__ == "__main__":
    unittest.main()
