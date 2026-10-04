#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SCRIPT = SCRIPTS / "audit_u5c_occlusion.py"
spec = importlib.util.spec_from_file_location("audit_u5c_occlusion", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class U5cOcclusionAuditTests(unittest.TestCase):
    def test_pair_metrics_separate_new_foreground_leakage_and_shared_flips(self):
        faro = np.asarray([1.0, 1.0, 1.0, 1.0, 1.0, 1.0], dtype=np.float32)
        reference = np.asarray([np.inf, 1.0, 1.0, 1.2, np.inf, 1.0], dtype=np.float32)
        challenger = np.asarray([0.8, np.inf, 1.02, 0.8, 1.0, 1.2], dtype=np.float32)

        metrics = module.pair_metrics(challenger, reference, faro)

        self.assertEqual(metrics["faroValidPixelCount"], 6)
        self.assertEqual(metrics["challengerOnlyCount"], 2)
        self.assertEqual(metrics["referenceOnlyCount"], 1)
        self.assertEqual(metrics["bothFiniteCount"], 3)
        self.assertAlmostEqual(metrics["challengerOnlyCoverageFraction"], 2.0 / 6.0)
        self.assertAlmostEqual(metrics["referenceOnlyCoverageFraction"], 1.0 / 6.0)
        self.assertAlmostEqual(metrics["bothFiniteFraction"], 3.0 / 6.0)

        self.assertEqual(metrics["challengerOnlyForegroundWrongCount"], 1)
        self.assertEqual(metrics["challengerOnlyBackgroundWrongCount"], 0)
        self.assertEqual(metrics["challengerOnlyWithin5cmCount"], 1)
        self.assertAlmostEqual(metrics["challengerOnlyForegroundWrongShare"], 0.5)
        self.assertAlmostEqual(metrics["challengerOnlyWithin5cmShare"], 0.5)

        self.assertEqual(metrics["referenceCorrectChallengerWrongCount"], 1)
        self.assertEqual(metrics["challengerCorrectReferenceWrongCount"], 0)
        self.assertAlmostEqual(
            metrics["referenceCorrectChallengerWrongFractionOfFaroValid"], 1.0 / 6.0
        )
        self.assertAlmostEqual(metrics["medianRenderedDepthShiftMetres"], 0.02, places=6)
        self.assertAlmostEqual(metrics["medianAbsoluteErrorShiftMetres"], 0.02, places=6)

    def test_tie_tolerance_does_not_award_near_equal_errors(self):
        faro = np.asarray([1.0], dtype=np.float64)
        reference = np.asarray([1.1], dtype=np.float64)
        challenger = np.asarray([0.9000005], dtype=np.float64)
        metrics = module.pair_metrics(
            challenger,
            reference,
            faro,
            tie_tolerance=1.0e-6,
        )
        self.assertEqual(metrics["bothFiniteChallengerCloserCount"], 0)
        self.assertEqual(metrics["bothFiniteReferenceCloserCount"], 0)

    def test_scene_summary_uses_view_mean_and_pooled_counts(self):
        records = []
        for index in range(8):
            record = {key: 0 for key in module.COUNT_KEYS}
            for key in module.FRACTION_KEYS:
                record[key] = index / 10.0
            for key in module.MEDIAN_KEYS:
                record[key] = index / 100.0
            record["faroValidPixelCount"] = 10
            record["challengerOnlyCount"] = 2
            record["challengerOnlyForegroundWrongCount"] = 1
            record["challengerOnlyBackgroundWrongCount"] = 0
            record["challengerOnlyWithin5cmCount"] = 1
            records.append(record)

        summary = module.scene_summary(records)
        self.assertAlmostEqual(summary["challengerOnlyCoverageFractionMean"], 0.35)
        self.assertAlmostEqual(
            summary["medianRenderedDepthShiftMetresMeanAcrossDefinedTargets"], 0.035
        )
        self.assertEqual(summary["pooledCounts"]["faroValidPixelCount"], 80)
        self.assertEqual(summary["pooledCounts"]["challengerOnlyCount"], 16)
        self.assertAlmostEqual(summary["pooledChallengerOnlyForegroundWrongShare"], 0.5)
        self.assertAlmostEqual(summary["pooledChallengerOnlyWithin5cmShare"], 0.5)

    def test_bootstrap_is_deterministic(self):
        values = [0.1, 0.2, 0.3, 0.4, 0.5]
        a = module.paired_bootstrap_median(values, replicates=2000, seed=42)
        b = module.paired_bootstrap_median(values, replicates=2000, seed=42)
        self.assertEqual(a, b)
        self.assertEqual(a["median"], 0.3)
        self.assertEqual(a["definedSceneCount"], 5)


if __name__ == "__main__":
    unittest.main()
