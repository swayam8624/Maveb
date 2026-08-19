import importlib.util
from pathlib import Path
import struct
import unittest


def load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "arkit_uncertainty_samples.py"
    spec = importlib.util.spec_from_file_location("arkit_uncertainty_samples", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


samples = load_module()


class ArkitUncertaintySamplesTests(unittest.TestCase):
    def test_confidence_mapping_preserves_three_ordinal_levels(self):
        self.assertEqual(samples.arkit_confidence_probability(0), 0.0)
        self.assertEqual(samples.arkit_confidence_probability(1), 0.5)
        self.assertEqual(samples.arkit_confidence_probability(2), 1.0)
        with self.assertRaises(ValueError):
            samples.arkit_confidence_probability(3)

    def test_identity_native_arkit_pose_becomes_image_aligned_ray(self):
        matrix = [
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
            4.0,
            5.0,
            6.0,
            1.0,
        ]
        origin, direction = samples.image_aligned_ray_from_arkit_matrix(
            matrix,
            x=12,
            y=8,
            fx=4.0,
            fy=2.0,
            cx=10.0,
            cy=6.0,
        )
        self.assertEqual(origin, (4.0, 5.0, 6.0))
        # Image ray is (+0.5,+1,+1); native ARKit camera axes are +Y up/-Z forward.
        self.assertEqual(direction, (0.5, -1.0, -1.0))

    def test_plane_readers_respect_row_padding(self):
        float_row_stride = 12
        float_bytes = bytearray(float_row_stride * 2)
        struct.pack_into("<f", float_bytes, 0, 1.25)
        struct.pack_into("<f", float_bytes, 4, 2.5)
        struct.pack_into("<f", float_bytes, float_row_stride, 3.75)
        struct.pack_into("<f", float_bytes, float_row_stride + 4, 5.0)
        self.assertAlmostEqual(
            samples.read_float32_plane_value(
                bytes(float_bytes),
                x=1,
                y=1,
                width=2,
                height=2,
                row_stride_bytes=float_row_stride,
            ),
            5.0,
        )

        confidence = bytes([0, 2, 99, 1, 2, 99])
        self.assertEqual(
            samples.read_uint8_plane_value(
                confidence,
                x=1,
                y=1,
                width=2,
                height=2,
                row_stride_bytes=3,
            ),
            2,
        )

    def test_malformed_pose_is_rejected(self):
        with self.assertRaises(ValueError):
            samples.image_aligned_ray_from_arkit_matrix(
                [1.0] * 15,
                x=0,
                y=0,
                fx=1.0,
                fy=1.0,
                cx=0.0,
                cy=0.0,
            )


if __name__ == "__main__":
    unittest.main()
