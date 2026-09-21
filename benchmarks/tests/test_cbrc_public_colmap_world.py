from __future__ import annotations

import importlib.util
import json
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


seed = load_module(
    "cbrc_seed_colmap_world",
    "benchmarks/scripts/cbrc_seed_colmap_world.py",
)
fetch = load_module(
    "cbrc_fetch_public_dataset",
    "benchmarks/scripts/cbrc_fetch_public_dataset.py",
)
prepare = load_module(
    "cbrc_prepare_real_campaign_public_test",
    "benchmarks/scripts/cbrc_prepare_real_campaign.py",
)


def make_points_text(path: Path, count: int = 180) -> None:
    lines = [
        "# POINT3D_ID X Y Z R G B ERROR TRACK[]",
    ]
    for index in range(count):
        x = (index % 10) * 0.12
        y = ((index // 10) % 9) * 0.11
        z = 1.0 + (index // 90) * 0.3
        r = 40 + index % 180
        g = 80 + index % 120
        b = 120 + index % 100
        track = "1 0 2 1 3 2 4 3"
        lines.append(
            f"{index + 1} {x} {y} {z} {r} {g} {b} 0.5 {track}"
        )
    path.write_text("\n".join(lines) + "\n")


class PublicColmapWorldTests(unittest.TestCase):
    def test_colmap_text_seeds_native_world_consumable_by_campaign(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "scene" / "sparse" / "0"
            model.mkdir(parents=True)
            make_points_text(model / "points3D.txt")

            raw, source = seed.load_points(model)
            selected, filtering = seed.select_points(raw, 3, None, 1000)
            canonical, scale = seed.canonicalize(selected, 2.0)
            minimum, maximum = seed.bounds(canonical)
            diag = seed.diagonal(minimum, maximum)
            cell = diag / 7.0
            gaussian_scale = 0.02
            owners, entities = seed.spatial_partition(
                canonical,
                cell,
                gaussian_scale,
                float(filtering["maximumReprojectionError"]),
            )
            self.assertGreaterEqual(len(entities), 2)
            self.assertEqual(len(owners), len(canonical))
            self.assertEqual(scale["scaleSource"], "canonical-normalization-not-measured")

            world = root / "world.aetherworld"
            world_payload = {
                "schemaVersion": 1,
                "nextEntityId": len(entities) + 1,
                "snapshots": [
                    {
                        "revision": 1,
                        "timestamp": 1_000_000_000,
                        "entities": entities,
                    }
                ],
            }
            seed.atomic_text(world, json.dumps(world_payload))
            seed.atomic_bytes(
                Path(str(world) + ".gaussians.r1.bin"),
                seed.encode_gaussians(canonical, gaussian_scale, 0.85),
            )
            seed.atomic_bytes(
                Path(str(world) + ".ownership.r1.bin"),
                seed.encode_ownership(owners),
            )

            candidate = prepare.inspect_archive(world)
            self.assertEqual(candidate.gaussian_count, len(canonical))
            self.assertGreaterEqual(len(candidate.entities), 2)
            self.assertEqual(source.name, "points3D.txt")

    def test_colmap_binary_parser_matches_standard_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "points3D.bin"
            with path.open("wb") as stream:
                stream.write(struct.pack("<Q", 2))
                for point_id, x in [(7, 1.25), (8, 2.5)]:
                    stream.write(
                        struct.pack(
                            "<QdddBBBd",
                            point_id,
                            x,
                            2.0,
                            3.0,
                            10,
                            20,
                            30,
                            0.25,
                        )
                    )
                    stream.write(struct.pack("<Q", 3))
                    for image_id, point2d in [(1, 2), (3, 4), (5, 6)]:
                        stream.write(struct.pack("<ii", image_id, point2d))
            points = list(seed.read_points_binary(path))
            self.assertEqual([p.point_id for p in points], [7, 8])
            self.assertEqual(points[0].track_length, 3)
            self.assertAlmostEqual(points[1].xyz[0], 2.5)

    def test_fetcher_extracts_only_selected_sparse_members(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "bundle.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("tandt/train/sparse/0/points3D.txt", "1 0 0 0 1 2 3 0.1\n")
                handle.writestr("tandt/train/images/private.jpg", b"not-needed")
                handle.writestr("db/playroom/sparse/0/points3D.txt", "ignored")
            output = root / "out"
            report = fetch.safe_extract_selected(
                archive,
                output,
                [
                    {
                        "id": "tandt-train",
                        "memberPrefix": "tandt/train/sparse/0/",
                    }
                ],
            )
            self.assertEqual(len(report), 1)
            self.assertTrue(
                (output / "tandt-train" / "sparse" / "0" / "points3D.txt").is_file()
            )
            self.assertFalse((output / "tandt-train" / "images").exists())


if __name__ == "__main__":
    unittest.main()
