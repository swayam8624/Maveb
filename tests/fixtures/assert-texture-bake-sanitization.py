#!/usr/bin/env python3

import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zlib


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(
            ">I",
            zlib.crc32(kind + payload) & 0xFFFFFFFF,
        )
    )


def write_png(path: Path) -> None:
    width = 4
    height = 4

    rows = []

    for y in range(height):
        row = bytearray([0])

        for x in range(width):
            row.extend(
                (
                    64 + 32 * x,
                    64 + 32 * y,
                    160,
                    255,
                )
            )

        rows.append(bytes(row))

    raw = b"".join(rows)

    payload = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(
            b"IHDR",
            struct.pack(
                ">IIBBBBB",
                width,
                height,
                8,
                6,
                0,
                0,
                0,
            ),
        )
        + png_chunk(
            b"IDAT",
            zlib.compress(raw, 9),
        )
        + png_chunk(b"IEND", b"")
    )

    path.write_bytes(payload)


def execute(
    tool: Path,
    root: Path,
    output: Path,
) -> dict:
    command = [
        str(tool),
        str(root / "mesh.ply"),
        "--colmap",
        str(root / "colmap"),
        "--metric-rig",
        str(root / "rig.json"),
        "--images",
        str(root / "images"),
        "--output",
        str(output),
        "--atlas-size",
        "32",
        "--visibility-size",
        "8",
        "--max-image-dimension",
        "4",
        "--json",
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "maveb-texture-bake failed\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    lines = [
        line
        for line in result.stdout.splitlines()
        if line.strip()
    ]

    if not lines:
        raise RuntimeError(
            "maveb-texture-bake produced no JSON output"
        )

    return json.loads(lines[-1])


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(
            "usage: assert-texture-bake-sanitization.py "
            "<maveb-texture-bake> <work-directory>"
        )

    tool = Path(sys.argv[1]).resolve()
    root = Path(sys.argv[2]).resolve()

    if root.exists():
        shutil.rmtree(root)

    (root / "images").mkdir(parents=True)
    (root / "colmap").mkdir()

    # Face 0:
    #   ordinary valid triangle.
    #
    # Face 1:
    #   all THREE indices are distinct, so ProxyPlyLoader
    #   accepts it. Geometrically, however, the vertices are
    #   almost collinear:
    #
    #       |cross(b-a, d-a)|^2 ~= 1e-10
    #
    #   which is below TextureBaker's 1e-8 threshold.
    #
    # This reproduces the actual loader -> baker compatibility
    # boundary seen in the captured-world TSDF proxy.

    (root / "mesh.ply").write_text(
        """ply
format ascii 1.0
element vertex 4
property float x
property float y
property float z
property float nx
property float ny
property float nz
element face 2
property list uchar int vertex_indices
end_header
-0.5 -0.5 2.0 0.0 0.0 -1.0
0.5 -0.5 2.0 0.0 0.0 -1.0
-0.5 0.5 2.0 0.0 0.0 -1.0
0.0 -0.49999 2.0 0.0 0.0 -1.0
3 0 1 2
3 0 1 3
"""
    )

    (root / "colmap" / "cameras.txt").write_text(
        "# Camera list\n"
        "1 PINHOLE 4 4 4 4 1.5 1.5\n"
    )

    (root / "rig.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "accepted": True,
                "metricCameras": [
                    {
                        "imageId": 1,
                        "cameraId": 1,
                        "imageName": "frame.png",
                        "cameraToMetricWorld": {
                            "translation": [
                                0.0,
                                0.0,
                                0.0,
                            ],
                            "orientationWxyz": [
                                1.0,
                                0.0,
                                0.0,
                                0.0,
                            ],
                        },
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    write_png(root / "images" / "frame.png")

    output_a = root / "a.glb"
    output_b = root / "b.glb"

    result_a = execute(tool, root, output_a)
    result_b = execute(tool, root, output_b)

    provenance_a = Path(
        str(output_a) + ".provenance.json"
    )

    provenance_b = Path(
        str(output_b) + ".provenance.json"
    )

    if output_a.read_bytes() != output_b.read_bytes():
        raise AssertionError(
            "independent sanitized GLBs differ"
        )

    if (
        provenance_a.read_bytes()
        != provenance_b.read_bytes()
    ):
        raise AssertionError(
            "independent sanitization provenance differs"
        )

    for result in (result_a, result_b):
        assert result["ok"] is True
        assert result["sourceTriangles"] == 2
        assert result["triangles"] == 1
        assert (
            result["droppedDegenerateTriangles"]
            == 1
        )

    provenance = json.loads(
        provenance_a.read_text()
    )

    sanitization = (
        provenance["configuration"]
        ["meshSanitization"]
    )

    assert sanitization["policy"] == (
        "drop-only-texture-baker-degenerate-triangles"
    )

    assert sanitization["sourceTriangles"] == 2
    assert sanitization["retainedTriangles"] == 1

    assert (
        sanitization["droppedDegenerateTriangles"]
        == 1
    )

    assert (
        sanitization["vertexPositionsModified"]
        is False
    )

    threshold = sanitization[
        "minimumCrossLengthSquared"
    ]

    assert 9.0e-9 < threshold < 1.1e-8

    assert provenance["result"]["triangles"] == 1
    assert provenance["result"]["cameras"] == 1
    assert provenance["result"]["texturedTexels"] > 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
