#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_u3b_dense_tsdf_confirmatory.py"
spec = importlib.util.spec_from_file_location("run_u3b_dense_tsdf_confirmatory", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class RunU3bConfirmatoryTests(unittest.TestCase):
    def test_engine_mapping_is_exactly_preregistered_method_set(self):
        protocol_path = Path(__file__).resolve().parents[1] / "experiments" / "metric-uncertainty-u3b-relative-confidence-transfer-v1.json"
        protocol = json.loads(protocol_path.read_text())
        protocol_methods = tuple(item["id"] for item in protocol["methods"])
        self.assertEqual(protocol_methods, module.METHODS)
        self.assertEqual(
            module.ENGINE_MAPPING["u3v1-absolute-inverse-variance"],
            ("legacy", "calibrated-inverse-variance"),
        )
        self.assertEqual(
            module.ENGINE_MAPPING["relative-confidence-precision"],
            ("relative", "calibrated-inverse-variance"),
        )
        self.assertEqual(
            module.ENGINE_MAPPING["relative-confidence-shuffled"],
            ("relative", "calibrated-shuffled-confidence"),
        )

    def test_paired_bootstrap_is_deterministic(self):
        values = [0.2, 0.1, -0.1, 0.3, 0.05]
        first = module.paired_bootstrap_median(values, replicates=2000, seed=42)
        second = module.paired_bootstrap_median(values, replicates=2000, seed=42)
        self.assertEqual(first, second)
        self.assertEqual(first["median"], 0.1)

    def test_percentile_uses_nearest_tie_lower(self):
        self.assertEqual(module.percentile_nearest([0.0, 1.0, 2.0], 0.25), 0.0)
        self.assertEqual(module.percentile_nearest([0.0, 1.0, 2.0], 0.75), 1.0)

    def test_runtime_replay_exact_match_passes(self):
        expected = {
            "meshSha256": "abc",
            "chamferMeanMetres": 0.123,
            "fScoreAt5cm": 0.456,
            "vertices": 10,
            "triangles": 20,
        }
        metrics = {
            "chamferMeanMetres": 0.123,
            "fScore": 0.456,
            "vertices": 10,
            "triangles": 20,
        }
        module.verify_runtime_replay(
            expected,
            scene="ca1m-test",
            method="uniform",
            mesh_sha256="abc",
            metrics=metrics,
        )

    def test_runtime_replay_mesh_change_fails(self):
        expected = {
            "meshSha256": "abc",
            "chamferMeanMetres": 0.123,
            "fScoreAt5cm": 0.456,
            "vertices": 10,
            "triangles": 20,
        }
        metrics = {
            "chamferMeanMetres": 0.123,
            "fScore": 0.456,
            "vertices": 10,
            "triangles": 20,
        }
        with self.assertRaises(RuntimeError):
            module.verify_runtime_replay(
                expected,
                scene="ca1m-test",
                method="uniform",
                mesh_sha256="different",
                metrics=metrics,
            )

    def test_runtime_replay_metric_change_fails(self):
        expected = {
            "meshSha256": "abc",
            "chamferMeanMetres": 0.123,
            "fScoreAt5cm": 0.456,
            "vertices": 10,
            "triangles": 20,
        }
        metrics = {
            "chamferMeanMetres": 0.124,
            "fScore": 0.456,
            "vertices": 10,
            "triangles": 20,
        }
        with self.assertRaises(RuntimeError):
            module.verify_runtime_replay(
                expected,
                scene="ca1m-test",
                method="uniform",
                mesh_sha256="abc",
                metrics=metrics,
            )

    def test_runtime_snapshot_requires_exactly_sixteen_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            payload = {
                "study": module.STUDY_ID,
                "status": "frozen-pre-fix-partial-reveal",
                "completedMethodCount": 15,
                "completed": [],
            }
            path.write_text(json.dumps(payload))
            with self.assertRaises(ValueError):
                module.load_runtime_replay_snapshot(path)


if __name__ == "__main__":
    unittest.main()
