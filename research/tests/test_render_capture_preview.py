import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
MODULE_PATH = ROOT / "research" / "tools" / "render_capture_preview.py"
SPEC = importlib.util.spec_from_file_location("render_capture_preview", MODULE_PATH)
preview = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(preview)


def make_capture(root: Path, delta: float = 0.0) -> Path:
    root.mkdir(parents=True)
    (root / "capture.json").write_text(
        json.dumps({"schemaVersion": 1, "width": 2, "height": 1}) + "\n"
    )
    pixels = [
        (0.5 + delta, 0.25, 0.1, 1.0),
        (1.0, 0.5 + delta, 0.25, 1.0),
    ]
    (root / "color.rgba16f").write_bytes(
        b"".join(struct.pack("<eeee", *pixel) for pixel in pixels)
    )
    (root / "depth.r32f").write_bytes(struct.pack("<2f", 1.0, 2.0))
    (root / "ids.r32u").write_bytes(struct.pack("<2I", 1, 0))
    return root


class CapturePreviewTests(unittest.TestCase):
    def test_preview_decodes_exact_capture_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = make_capture(root / "capture")
            result = preview.convert(capture, root / "preview", 0.0)
            self.assertEqual(result["nonzeroIds"], 1)
            self.assertTrue((root / "preview" / "color.ppm").is_file())
            self.assertTrue((root / "preview" / "depth.pgm").is_file())
            self.assertTrue((root / "preview" / "ids.pgm").is_file())

    def test_comparison_reports_zero_for_identical_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = make_capture(root / "reference")
            candidate = make_capture(root / "candidate")
            result = preview.compare(reference, candidate, root / "comparison", 8.0)
            self.assertEqual(result["rmseRgb"], 0.0)
            self.assertEqual(result["meanAbsoluteRgb"], 0.0)

    def test_comparison_detects_pixel_difference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = make_capture(root / "reference")
            candidate = make_capture(root / "candidate", 0.1)
            result = preview.compare(reference, candidate, root / "comparison", 8.0)
            self.assertGreater(result["rmseRgb"], 0.0)
            self.assertGreater(result["maximumAbsoluteRgb"], 0.0)


if __name__ == "__main__":
    unittest.main()
