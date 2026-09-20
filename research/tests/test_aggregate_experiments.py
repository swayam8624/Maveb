import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[2] / "research" / "tools" / "aggregate_experiments.py"
SPEC = importlib.util.spec_from_file_location("aggregate_experiments", MODULE_PATH)
agg = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(agg)


def run(identifier, psnr, gpu, memory):
    return {
        "schemaVersion": 1,
        "experiment_id": identifier,
        "quality": {"psnr": psnr},
        "performance": {"gpu_p95_ms": gpu, "peak_memory_mb": memory},
    }


class AggregateExperimentTests(unittest.TestCase):
    def test_pareto_rejects_strictly_dominated_configuration(self):
        runs = [
            run("balanced", 30.0, 10.0, 100.0),
            run("dominated", 29.0, 12.0, 120.0),
            run("quality", 32.0, 13.0, 130.0),
        ]
        objectives = [
            agg.Objective("performance.gpu_p95_ms", "min"),
            agg.Objective("performance.peak_memory_mb", "min"),
            agg.Objective("quality.psnr", "max"),
        ]
        front = agg.pareto_front(runs, objectives)
        self.assertEqual(front, ["balanced", "quality"])

    def test_discovery_ignores_non_result_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "good.json").write_text(json.dumps(run("good", 30, 10, 100)))
            (root / "other.json").write_text(json.dumps({"schemaVersion": 1, "foo": 2}))
            (root / "broken.json").write_text("{")
            found = agg.discover([root])
            self.assertEqual([agg.experiment_id(data) for _, data in found], ["good"])

    def test_flatten_preserves_per_domain_ulr(self):
        data = run("x", 30, 10, 100)
        data["locality"] = {
            "domains": {
                "gaussiansInspected": {"incremental": 10, "full": 1000, "ratio": 0.01},
                "gpuPublicationBytes": {"incremental": 2560, "full": 256000, "ratio": 0.01},
            }
        }
        row = agg.flatten_selected(Path("x.json"), data)
        self.assertEqual(row["ulr_gaussiansInspected"], 0.01)
        self.assertEqual(row["ulr_gpuPublicationBytes"], 0.01)


if __name__ == "__main__":
    unittest.main()
