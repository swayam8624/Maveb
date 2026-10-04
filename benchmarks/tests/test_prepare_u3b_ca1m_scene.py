#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SCRIPT = SCRIPTS / "prepare_u3b_ca1m_scene.py"
spec = importlib.util.spec_from_file_location("prepare_u3b_ca1m_scene", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class PrepareU3bSceneTests(unittest.TestCase):
    def adapter(self):
        return {
            "relativeManifestUncertaintyConfig": {
                "minimumSigmaMetres": 1.0,
                "maximumSigmaMetres": 7.0,
                "depthNoiseFloorMetres": 1.0,
                "depthNoiseQuadraticMetresPerMetreSquared": 0.0,
                "sensorConfidencePenalty": 5.990146384791633,
                "poseTranslationFloorMetres": 0.0,
                "poseTranslationScaleMetres": 0.0,
                "referenceSigmaMetres": 1.0,
                "minimumPrecisionWeight": 1e-12,
                "maximumPrecisionWeight": 1.0,
            },
            "equivalence": {
                "expectedWeights": {
                    "confidenceU8_0": 0.020465740292285855,
                    "confidenceU8_128": 0.06302428158557383,
                    "confidenceU8_255": 1.0,
                }
            },
        }

    def test_relative_uncertainty_preserves_frozen_weights(self):
        config = module.relative_uncertainty(self.adapter())
        k = config["sensorConfidencePenalty"]
        self.assertAlmostEqual(1.0 / (1.0 + k) ** 2, 0.020465740292285855, places=15)
        self.assertAlmostEqual(
            1.0 / (1.0 + k * (1.0 - 128.0 / 255.0)) ** 2,
            0.06302428158557383,
            places=15,
        )
        self.assertLess(config["minimumPrecisionWeight"], 0.020465740292285855)
        self.assertGreaterEqual(config["maximumSigmaMetres"], 1.0 + k)

    def test_relative_uncertainty_rejects_active_floor(self):
        adapter = self.adapter()
        adapter["relativeManifestUncertaintyConfig"]["minimumPrecisionWeight"] = 0.03
        with self.assertRaises(ValueError):
            module.relative_uncertainty(adapter)

    def test_engine_manifest_keeps_compatibility_and_research_ids_separate(self):
        manifest = module.engine_manifest(
            scene="ca1m-1",
            video_id="1",
            frames=[{"frameId": 1}],
            bounds={"originMetres": [0, 0, 0]},
            uncertainty={"sensorConfidencePenalty": 5.0},
            reference={"retainedPoints": 1},
            research_role="relative-confidence-precision",
            adapter_sha="abc",
        )
        self.assertEqual(manifest["study"], module.ENGINE_STUDY_ID)
        self.assertEqual(manifest["researchStudy"], module.STUDY_ID)
        self.assertEqual(manifest["researchMethodFamily"], "relative-confidence-precision")
        self.assertEqual(manifest["u3bEngineAdapterSha256"], "abc")


if __name__ == "__main__":
    unittest.main()
