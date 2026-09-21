from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/cbrc_calibrate_work.py"
spec = importlib.util.spec_from_file_location("cbrc_calibrate_work", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class CBRCCalibrateWorkTests(unittest.TestCase):
    def test_median_is_frozen_per_native_unit(self):
        rows = [
            {
                "domain": "gaussiansUpdated",
                "unit": "gaussians",
                "units": 100,
                "elapsed_ms": elapsed,
                "baseline_ms": 1.0,
                "calibration_id": "fixture",
            }
            for elapsed in (2.0, 3.0, 4.0, 5.0, 6.0)
        ]
        result = mod.calibrate(rows, version="fixture-v1", minimum_repeats=5)
        self.assertAlmostEqual(
            result["domains"]["gaussiansUpdated"]["cost_per_unit"],
            0.03,
        )
        self.assertEqual(
            result["domains"]["gaussiansUpdated"]["calibration_samples"],
            5,
        )

    def test_too_few_repeats_fails_closed(self):
        rows = [
            {
                "domain": "gpuPublicationBytes",
                "unit": "bytes",
                "units": 1000,
                "elapsed_ms": 1.0,
            }
        ]
        with self.assertRaisesRegex(ValueError, "requires at least"):
            mod.calibrate(rows, version="fixture-v1", minimum_repeats=2)

    def test_unit_change_is_rejected(self):
        rows = [
            {
                "domain": "x",
                "unit": "blocks",
                "units": 1,
                "elapsed_ms": 1,
            },
            {
                "domain": "x",
                "unit": "bytes",
                "units": 1,
                "elapsed_ms": 1,
            },
        ]
        with self.assertRaisesRegex(ValueError, "changes native units"):
            mod.calibrate(rows, version="fixture-v1", minimum_repeats=1)


if __name__ == "__main__":
    unittest.main()
