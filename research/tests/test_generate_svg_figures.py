import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[2] / "research" / "tools" / "generate_svg_figures.py"
SPEC = importlib.util.spec_from_file_location("generate_svg_figures", MODULE_PATH)
fig = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(fig)


class FigureGeneratorTests(unittest.TestCase):
    def test_scatter_svg_contains_raw_point_and_labels(self):
        rows = [
            {"experiment_id": "a", "gpu_p95_ms": "8.0", "psnr": "30.0"},
            {"experiment_id": "b", "gpu_p95_ms": "12.0", "psnr": "31.0"},
        ]
        svg = fig.scatter_svg(rows, "gpu_p95_ms", "psnr", "GPU p95", "PSNR", "Test")
        self.assertIn("<svg", svg)
        self.assertIn("<circle", svg)
        self.assertIn("GPU p95", svg)
        self.assertIn("<title>a</title>", svg)

    def test_cli_inputs_can_generate_ulr_figure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path = root / "runs.csv"
            with csv_path.open("w", newline="") as stream:
                writer = csv.DictWriter(
                    stream,
                    fieldnames=[
                        "experiment_id",
                        "gpu_p95_ms",
                        "psnr",
                        "changed_fraction",
                        "ulr_gaussiansInspected",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "experiment_id": "a",
                        "gpu_p95_ms": 8,
                        "psnr": 30,
                        "changed_fraction": 0.01,
                        "ulr_gaussiansInspected": 0.02,
                    }
                )
                writer.writerow(
                    {
                        "experiment_id": "b",
                        "gpu_p95_ms": 10,
                        "psnr": 31,
                        "changed_fraction": 0.1,
                        "ulr_gaussiansInspected": 0.11,
                    }
                )
            rows = fig.read_rows(csv_path)
            svg = fig.scatter_svg(
                rows,
                "changed_fraction",
                "ulr_gaussiansInspected",
                "Changed",
                "ULR",
                "Locality",
            )
            self.assertIn("Locality", svg)
            self.assertEqual(svg.count("<circle"), 2)


if __name__ == "__main__":
    unittest.main()
