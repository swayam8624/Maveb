from __future__ import annotations

import importlib.util
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


freeze = load_module(
    "cbrc_freeze_reviewer_certificate_v5",
    "benchmarks/scripts/cbrc_freeze_reviewer_certificate_v5.py",
)


class ReviewerCertificateV5ProtocolTests(unittest.TestCase):
    def test_frozen_matrix_matches_declared_certificate_experiment(self):
        self.assertEqual(freeze.EDIT_FAMILIES, ("opacity", "translation"))
        self.assertEqual(
            freeze.EPSILON_LEVELS_255,
            (1.0, 2.0, 4.0, 8.0, 16.0, 32.0),
        )
        self.assertEqual(
            freeze.RESIDUAL_SCALES,
            (0.0, 1.0 / 4096.0, 1.0 / 1024.0, 1.0 / 256.0),
        )
        self.assertEqual(len(freeze.SEVERITY_PROFILES), 4)
        self.assertEqual(
            {float(profile["delta_fraction"]) for profile in freeze.SEVERITY_PROFILES},
            {0.06},
        )
        self.assertEqual(
            {float(profile["history_weight"]) for profile in freeze.SEVERITY_PROFILES},
            {0.90},
        )
        self.assertTrue(
            all(bool(profile["history_stable"]) for profile in freeze.SEVERITY_PROFILES)
        )

    def test_matrix_size_is_fixed_before_outcomes(self):
        datasets = 4
        expected = (
            datasets
            * len(freeze.SEVERITY_PROFILES)
            * len(freeze.EDIT_FAMILIES)
            * len(freeze.RESIDUAL_SCALES)
            * len(freeze.EPSILON_LEVELS_255)
        )
        self.assertEqual(expected, 768)

    def test_runner_shell_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(ROOT / "run_reviewer_certificate_v5.sh")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
