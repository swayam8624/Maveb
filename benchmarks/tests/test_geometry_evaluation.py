import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/evaluate_geometry.py"
SPEC = importlib.util.spec_from_file_location("evaluate_geometry", MODULE_PATH)
geometry = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = geometry
SPEC.loader.exec_module(geometry)

def usable_numpy() -> bool:
    try:
        import numpy as np
        return callable(getattr(np, "asarray", None))
    except (ImportError, AttributeError):
        return False


NUMPY_AVAILABLE = usable_numpy()


class GeometryEvaluationTests(unittest.TestCase):
    def test_fscore(self):
        result = geometry.f_score([0.0, 0.01], [0.0, 0.01], 0.02)
        self.assertEqual(result["precision"], 1.0)
        self.assertEqual(result["recall"], 1.0)
        self.assertEqual(result["fScore"], 1.0)

    def test_percentile(self):
        self.assertEqual(geometry.percentile([1, 2, 3, 4, 5], 0.95), 5.0)

    @unittest.skipUnless(
        NUMPY_AVAILABLE,
        "NumPy is supplied by Maveb's pinned proxy/evaluation environment, not bare CPU CI",
    )
    def test_umeyama(self):
        import numpy as np

        source = np.asarray([[0, 0, 0], [1, 0, 0], [0, 2, 0], [0, 0, 3]], float)
        rotation = np.asarray([[0, -1, 0], [1, 0, 0], [0, 0, 1]], float)
        scale = 2.5
        translation = np.asarray([4, -3, 7], float)
        target = (scale * rotation @ source.T).T + translation
        transform, recovered_scale = geometry.umeyama_similarity(source, target)
        aligned = (transform[:3, :3] @ source.T).T + transform[:3, 3]
        self.assertAlmostEqual(recovered_scale, scale, places=8)
        self.assertTrue(np.allclose(aligned, target, atol=1e-8))

    @unittest.skipUnless(
        NUMPY_AVAILABLE,
        "NumPy is supplied by Maveb's pinned proxy/evaluation environment, not bare CPU CI",
    )
    def test_parse_colmap(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "images.txt"
            path.write_text(
                "# Image list\n"
                "1 1 0 0 0 0 0 0 1 image.jpg\n"
                "10 20 -1\n"
            )
            centers = geometry.parse_colmap_camera_centers(path)
            self.assertIn("image.jpg", centers)
            self.assertEqual(tuple(centers["image.jpg"]), (0.0, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
