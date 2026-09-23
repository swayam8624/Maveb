from __future__ import annotations

import importlib.util
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


freeze = load(
    "cbrc_freeze_broad_campaign_test",
    ROOT / "benchmarks/scripts/cbrc_freeze_broad_campaign.py",
)
campaign = load(
    "cbrc_campaign_multiedit_test",
    ROOT / "benchmarks/scripts/cbrc_campaign.py",
)


def case() -> dict:
    return {
        "id": "fixture",
        "epsilon": 1 / 255,
        "matrix_tags": {
            "delta_fraction": 0.1,
            "applied_delta_world": 0.2,
            "sign": -1,
            "axis": 2,
        },
        "revision": {
            "archive": "/tmp/world.aetherworld",
            "entity": 1,
            "target": [0.0, 0.0, 1.0],
            "timestamp": 200,
            "camera": {},
        },
    }


class BroadMultiEditFreezeTests(unittest.TestCase):
    def test_fifteen_slots_are_deterministically_balanced(self):
        families = []
        for index in range(15):
            value = case()
            families.append(freeze.apply_edit_family(value, index))
        self.assertEqual(
            Counter(families),
            Counter(
                {
                    "translation": 4,
                    "rotation": 4,
                    "uniform-scale": 4,
                    "opacity": 3,
                }
            ),
        )

    def test_non_translation_edits_replace_translation_target(self):
        rotation = case()
        self.assertEqual(freeze.apply_edit_family(rotation, 1), "rotation")
        self.assertNotIn("target", rotation["revision"])
        self.assertEqual(rotation["revision"]["edit"]["axis"], [0.0, 0.0, 1.0])
        self.assertLess(rotation["revision"]["edit"]["radians"], 0.0)

        scale = case()
        self.assertEqual(freeze.apply_edit_family(scale, 2), "uniform-scale")
        self.assertNotIn("target", scale["revision"])
        self.assertLess(scale["revision"]["edit"]["factor"], 1.0)
        self.assertGreater(scale["revision"]["edit"]["factor"], 0.0)

        appearance = case()
        self.assertEqual(freeze.apply_edit_family(appearance, 3), "opacity")
        self.assertNotIn("target", appearance["revision"])
        self.assertLess(appearance["revision"]["edit"]["logit_delta"], 0.0)

    def test_three_case_smoke_does_not_require_unfrozen_high_or_full_outcome(self):
        policy = freeze.broad_gate_policy(
            [
                {"coupling_regime": "low"},
                {"coupling_regime": "low"},
                {"coupling_regime": "low"},
            ]
        )
        self.assertFalse(policy["require_full_fallback"])
        self.assertFalse(policy["require_high_coupling"])
        self.assertEqual(
            policy["metadata"]["frozenCouplingRegimes"],
            ["low"],
        )

    def test_paper_matrix_requires_high_coverage_but_not_a_particular_fallback_outcome(self):
        policy = freeze.broad_gate_policy(
            [
                {"coupling_regime": "low"},
                {"coupling_regime": "medium"},
                {"coupling_regime": "high"},
                {"coupling_regime": "adversarial"},
            ]
        )
        self.assertFalse(policy["require_full_fallback"])
        self.assertTrue(policy["require_high_coupling"])
        self.assertEqual(
            policy["metadata"]["fullFallback"],
            "observed-outcome-not-required",
        )

    def test_capture_case_builds_rotation_cli(self):
        value = case()
        freeze.apply_edit_family(value, 1)
        captured = []
        original = campaign.run
        try:
            with tempfile.TemporaryDirectory() as directory:
                case_dir = Path(directory)
                def fake_run(command):
                    captured.append(command)
                    output = case_dir / "capture"
                    output.mkdir(parents=True, exist_ok=True)
                    for name in (
                        "translation.json",
                        "certificate.json",
                        "native-planner-certificate.json",
                    ):
                        (output / name).write_text("{}\n")
                campaign.run = fake_run
                campaign.capture_case(
                    value,
                    revision_tool=Path("/fake/maveb-cbrc-revision"),
                    case_dir=case_dir,
                )
        finally:
            campaign.run = original

        command = captured[0]
        self.assertIn("--edit-kind", command)
        self.assertIn("rotation", command)
        self.assertIn("--rotation-axis", command)
        self.assertIn("--rotation-radians", command)
        self.assertNotIn("--target", command)

    def test_legacy_translation_case_stays_supported(self):
        value = case()
        value["revision"].pop("edit", None)
        captured = []
        original = campaign.run
        try:
            with tempfile.TemporaryDirectory() as directory:
                case_dir = Path(directory)
                def fake_run(command):
                    captured.append(command)
                    output = case_dir / "capture"
                    output.mkdir(parents=True, exist_ok=True)
                    for name in (
                        "translation.json",
                        "certificate.json",
                        "native-planner-certificate.json",
                    ):
                        (output / name).write_text("{}\n")
                campaign.run = fake_run
                campaign.capture_case(
                    value,
                    revision_tool=Path("/fake/maveb-cbrc-revision"),
                    case_dir=case_dir,
                )
        finally:
            campaign.run = original
        command = captured[0]
        self.assertIn("translation", command)
        self.assertIn("--target", command)


if __name__ == "__main__":
    unittest.main()
