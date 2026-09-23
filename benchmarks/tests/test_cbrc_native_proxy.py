from __future__ import annotations

import importlib.util
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/cbrc_native_proxy.py"
SPEC = importlib.util.spec_from_file_location("cbrc_native_proxy", MODULE_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(mod)


class NativeProxyTests(unittest.TestCase):
    def test_overlap_preserving_indices_are_centered_and_bounded(self):
        indices = mod.overlap_preserving_indices(100, 10, maximum_stride=4)
        self.assertEqual(len(indices), 10)
        self.assertLessEqual(max(b - a for a, b in zip(indices, indices[1:])), 4)
        self.assertGreater(indices[0], 0)
        self.assertLess(indices[-1], 99)

    def test_obj_mesh_triangulates_polygon_and_canonicalizes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "mesh.obj"
            source.write_text(
                "\n".join(
                    [
                        "v -2 -1 0",
                        "v 2 -1 0",
                        "v 2 1 0",
                        "v -2 1 0",
                        "f 1 2 3 4",
                    ]
                )
                + "\n"
            )
            mesh = mod.obj_mesh(source)
            self.assertEqual(len(mesh.vertices), 4)
            self.assertEqual(mesh.faces, [(0, 1, 2), (0, 2, 3)])
            provenance = mod.canonicalize(mesh, 2.0)
            minimum = [min(vertex[axis] for vertex in mesh.vertices) for axis in range(3)]
            maximum = [max(vertex[axis] for vertex in mesh.vertices) for axis in range(3)]
            diagonal = sum((maximum[i] - minimum[i]) ** 2 for i in range(3)) ** 0.5
            self.assertAlmostEqual(diagonal, 2.0, places=6)
            self.assertEqual(
                provenance["scaleSource"],
                "metric-source-canonicalized-for-broad-benchmark",
            )

    def test_write_ply_emits_proxy_loader_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proxy.ply"
            mesh = mod.Mesh(
                [
                    (0.0, 0.0, 0.0, 255, 0, 0),
                    (1.0, 0.0, 0.0, 0, 255, 0),
                    (0.0, 1.0, 0.0, 0, 0, 255),
                ],
                [(0, 1, 2)],
            )
            mod.write_ply(path, mesh)
            payload = path.read_text()
            self.assertIn("property float nx", payload)
            self.assertIn("property list uchar uint vertex_indices", payload)
            self.assertIn("3 0 1 2", payload)

    def test_bonn_uses_registered_depth_and_groundtruth_pose(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rgb = root / "rgb"
            depth = root / "depth"
            rgb.mkdir()
            depth.mkdir()
            for index in range(2):
                (rgb / f"{index}.png").write_bytes(b"rgb")
                (depth / f"{index}.png").write_bytes(b"depth")
            (root / "rgb.txt").write_text(
                "0.0 rgb/0.png\n0.1 rgb/1.png\n"
            )
            (root / "depth.txt").write_text(
                "0.0 depth/0.png\n0.1 depth/1.png\n"
            )
            (root / "groundtruth.txt").write_text(
                "0.0 0 0 0 0 0 0 1\n"
                "0.1 0.1 0 0 0 0 0 1\n"
            )

            width = height = 8
            depth_raw = b"".join(struct.pack("<H", 5000) for _ in range(width * height))
            rgb_raw = bytes([128, 64, 32]) * (width * height)

            def fake_decode(_ffmpeg, source, pixel_format):
                return depth_raw if pixel_format == "gray16le" else rgb_raw

            with mock.patch.object(mod, "ffmpeg_decode", side_effect=fake_decode):
                mesh, provenance = mod.build_bonn(
                    root,
                    maximum_frames=2,
                    maximum_vertices=1024,
                    ffmpeg="ffmpeg",
                    width=width,
                    height=height,
                    fx=4.0,
                    fy=4.0,
                    cx=3.5,
                    cy=3.5,
                )

            self.assertGreaterEqual(len(mesh.vertices), 64)
            self.assertGreater(len(mesh.faces), 0)
            self.assertEqual(provenance["convertedFrames"], 2)
            self.assertEqual(
                provenance["sourceRepresentation"],
                "bonn-registered-depth-plus-groundtruth-trajectory",
            )


if __name__ == "__main__":
    unittest.main()
