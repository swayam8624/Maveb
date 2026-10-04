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

    def test_arkit_timestamp_parser_matches_reference_second_field(self):
        self.assertEqual(
            mod.timestamp_from_path(Path("41069050_123.456_extra_999.png")),
            123.456,
        )
        self.assertEqual(
            mod.timestamp_from_path(Path("41069050_123.456.png")),
            123.456,
        )

    def test_arkit_pose_interpolates_between_sparse_vio_samples(self):
        pose_times = [0.0, 0.1]
        poses = {
            0.0: (
                [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                (0.0, 0.0, 0.0),
            ),
            0.1: (
                [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]],
                (1.0, 0.0, 0.0),
            ),
        }
        pose, mode, gap = mod.arkit_pose_at_timestamp(
            0.05,
            pose_times,
            poses,
            maximum_interpolation_gap=0.3,
        )
        self.assertIsNotNone(pose)
        assert pose is not None
        self.assertEqual(mode, "interpolated")
        self.assertAlmostEqual(gap, 0.1)
        self.assertAlmostEqual(pose[1][0], 0.5)
        # Midway between identity and +90 degree Z rotation is +45 degrees.
        root_half = 2.0 ** -0.5
        self.assertAlmostEqual(pose[0][0][0], root_half, places=6)
        self.assertAlmostEqual(pose[0][1][0], root_half, places=6)

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

    def test_rgb_is_centered_on_larger_depth_canvas(self):
        rgb = bytes(
            [
                255, 0, 0,
                0, 255, 0,
                0, 0, 255,
                255, 255, 255,
            ]
        )
        canvas, policy = mod.fit_rgb_to_depth_canvas(rgb, 2, 2, 4, 4)
        self.assertEqual(policy, "center-pad-or-crop-to-depth")
        self.assertEqual(len(canvas), 4 * 4 * 3)
        center = (1 * 4 + 1) * 3
        self.assertEqual(canvas[center : center + 3], bytes([255, 0, 0]))
        self.assertEqual(canvas[:3], bytes([0, 0, 0]))

    def test_arkit_uses_actual_depth_resolution_and_adapts_rgb(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "41069025"
            rgb_dir = root / "lowres_wide"
            depth_dir = root / "lowres_depth"
            intrinsics_dir = root / "lowres_wide_intrinsics"
            rgb_dir.mkdir(parents=True)
            depth_dir.mkdir()
            intrinsics_dir.mkdir()

            timestamps = (0.0, 0.1)
            (root / "lowres_wide.traj").write_text(
                "0.0 0 0 0 0 0 0\n"
                "0.1 0 0 0 0.1 0 0\n"
            )

            def write_png_header(path: Path, width: int, height: int) -> None:
                path.write_bytes(
                    mod.PNG_SIGNATURE
                    + struct.pack(">I", 13)
                    + b"IHDR"
                    + struct.pack(">II", width, height)
                )

            for timestamp in timestamps:
                stem = f"41069025_{timestamp:.1f}"
                write_png_header(rgb_dir / f"{stem}.png", 8, 6)
                write_png_header(depth_dir / f"{stem}.png", 12, 10)
                (intrinsics_dir / f"{stem}.pincam").write_text(
                    "8 6 4 4 6 5\n"
                )

            depth_raw = b"".join(
                struct.pack("<H", 1000) for _ in range(12 * 10)
            )
            rgb_raw = bytes([120, 80, 40]) * (8 * 6)

            def fake_decode(_ffmpeg, _source, pixel_format):
                return depth_raw if pixel_format == "gray16le" else rgb_raw

            with mock.patch.object(mod, "ffmpeg_decode", side_effect=fake_decode):
                mesh, provenance = mod.build_arkit(
                    root,
                    maximum_frames=2,
                    maximum_vertices=10000,
                    ffmpeg="ffmpeg",
                )

            self.assertGreaterEqual(len(mesh.vertices), 64)
            self.assertGreater(len(mesh.faces), 0)
            self.assertEqual(provenance["convertedFrames"], 2)
            self.assertEqual(provenance["appearance"]["resolutionAdaptedRgb"], 2)
            self.assertEqual(
                provenance["appearance"]["neutralRgbMissingOrDecodeFailed"], 0
            )

    def test_arkit_raw_depth_uses_interpolated_sparse_trajectory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "41069050"
            rgb_dir = root / "lowres_wide"
            depth_dir = root / "lowres_depth"
            intrinsics_dir = root / "lowres_wide_intrinsics"
            rgb_dir.mkdir(parents=True)
            depth_dir.mkdir()
            intrinsics_dir.mkdir()

            (root / "lowres_wide.traj").write_text(
                "0.0 0 0 0 0 0 0\n"
                "0.1 0 0 0 -0.1 0 0\n"
                "0.2 0 0 0 -0.2 0 0\n"
            )

            def write_png_header(path: Path, width: int, height: int) -> None:
                path.write_bytes(
                    mod.PNG_SIGNATURE
                    + struct.pack(">I", 13)
                    + b"IHDR"
                    + struct.pack(">II", width, height)
                )

            # RAW ARKitScenes depth can be sampled between the lower-rate VIO poses.
            timestamps = (0.025, 0.075)
            for timestamp in timestamps:
                stem = f"41069050_{timestamp:.3f}"
                write_png_header(rgb_dir / f"{stem}.png", 12, 10)
                write_png_header(depth_dir / f"{stem}.png", 12, 10)
                (intrinsics_dir / f"{stem}.pincam").write_text(
                    "12 10 6 6 5.5 4.5\n"
                )

            depth_raw = b"".join(
                struct.pack("<H", 1000) for _ in range(12 * 10)
            )
            rgb_raw = bytes([120, 80, 40]) * (12 * 10)

            def fake_decode(_ffmpeg, _source, pixel_format):
                return depth_raw if pixel_format == "gray16le" else rgb_raw

            with mock.patch.object(mod, "ffmpeg_decode", side_effect=fake_decode):
                mesh, provenance = mod.build_arkit(
                    root,
                    maximum_frames=2,
                    maximum_vertices=10000,
                    ffmpeg="ffmpeg",
                )

            self.assertGreaterEqual(len(mesh.vertices), 64)
            self.assertGreater(len(mesh.faces), 0)
            self.assertEqual(provenance["convertedFrames"], 2)
            self.assertEqual(provenance["poseAssociation"]["direct"], 0)
            self.assertEqual(provenance["poseAssociation"]["interpolated"], 2)
            self.assertEqual(provenance["skipped"]["pose"], 0)

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
