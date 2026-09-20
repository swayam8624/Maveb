from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/cbrc_campaign.py"
spec = importlib.util.spec_from_file_location("cbrc_campaign", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def row(*, fallback=False, coupling="low", actual=0.02, bound=0.03):
    return {
        "scene_id": "scene",
        "revision_id": "r",
        "coupling_regime": coupling,
        "fallback_full": fallback,
        "qois": {
            "rgb_linf": {
                "epsilon": 0.04,
                "certified_bound": 0.0 if fallback else bound,
                "measured_full_reference_error": 0.0 if fallback else actual,
            }
        },
    }


class CBRCCampaignTests(unittest.TestCase):
    def test_complete_campaign_gate_passes(self):
        rows = [
            row(),
            row(),
            row(),
            row(coupling="high"),
            row(fallback=True, coupling="adversarial"),
        ]
        result = mod.gate_rows(
            rows,
            {
                "minimum_revisions": 5,
                "minimum_scenes": 1,
                "require_local_success": True,
                "require_full_fallback": True,
                "require_high_coupling": True,
            },
        )
        self.assertTrue(result["pass"])

    def test_missing_fallback_fails(self):
        result = mod.gate_rows(
            [row() for _ in range(5)],
            {
                "minimum_revisions": 5,
                "minimum_scenes": 1,
                "require_local_success": True,
                "require_full_fallback": True,
                "require_high_coupling": False,
            },
        )
        self.assertFalse(result["pass"])
        self.assertFalse(result["gates"]["hasAutomaticFullFallback"])

    def test_certificate_violation_fails(self):
        rows = [row() for _ in range(4)] + [row(actual=0.04, bound=0.03)]
        result = mod.gate_rows(
            rows,
            {
                "minimum_revisions": 5,
                "minimum_scenes": 1,
                "require_local_success": True,
                "require_full_fallback": False,
                "require_high_coupling": False,
            },
        )
        self.assertFalse(result["pass"])
        self.assertFalse(result["gates"]["noCertificateViolations"])


if __name__ == "__main__":
    unittest.main()
