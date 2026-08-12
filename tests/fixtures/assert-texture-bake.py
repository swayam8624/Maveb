#!/usr/bin/env python3
import binascii
import hashlib
import json
import pathlib
import struct
import subprocess
import sys
import zlib


def png(path: pathlib.Path, width: int = 64, height: int = 64) -> None:
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            rows.extend((180 + x // 2, 25 + y // 3, 16))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", binascii.crc32(body))

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )


def run(command: list[str], expected: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != expected:
        raise AssertionError(
            f"exit {result.returncode}, expected {expected}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
    return result


def main() -> None:
    executable = pathlib.Path(sys.argv[1])
    root = pathlib.Path(sys.argv[2])
    root.mkdir(parents=True, exist_ok=True)
    model = root / "model"
    images = root / "images"
    model.mkdir(exist_ok=True)
    images.mkdir(exist_ok=True)
    (model / "cameras.txt").write_text("1 OPENCV 64 64 48 48 32 32 0 0 0 0\n")
    png(images / "sony.png")
    mesh = root / "metric.ply"
    mesh.write_text(
        "ply\nformat ascii 1.0\nelement vertex 4\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property float nx\nproperty float ny\nproperty float nz\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\n"
        "element face 2\nproperty list uchar int vertex_indices\nend_header\n"
        "-0.6 -0.6 2 0 0 -1 255 255 255\n"
        "0.6 -0.6 2 0 0 -1 255 255 255\n"
        "0.6 0.6 2 0 0 -1 255 255 255\n"
        "-0.6 0.6 2 0 0 -1 255 255 255\n"
        "3 0 1 2\n3 0 2 3\n"
    )
    rig = root / "rig.json"
    rig.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "accepted": True,
                "metricCameras": [
                    {
                        "cameraId": 1,
                        "imageName": "sony.png",
                        "cameraToMetricWorld": {
                            "translation": [0, 0, 0],
                            "orientationWxyz": [1, 0, 0, 0],
                        },
                    }
                ],
            },
            separators=(",", ":"),
        )
    )
    first = root / "first.glb"
    second = root / "second.glb"
    base = [
        str(executable), str(mesh), "--colmap", str(model), "--metric-rig", str(rig),
        "--images", str(images), "--atlas-size", "64", "--visibility-size", "64", "--json",
        "--max-image-dimension", "32",
    ]
    report = json.loads(run(base + ["--output", str(first)]).stdout)
    if not report["ok"] or report["coverage"] < 0.99 or report["cameras"] != 1:
        raise AssertionError(f"unexpected bake report: {report}")
    provenance = pathlib.Path(report["provenance"])
    evidence = json.loads(provenance.read_text())
    if evidence["result"]["glbSha256"] != hashlib.sha256(first.read_bytes()).hexdigest():
        raise AssertionError("provenance does not identify the emitted GLB")
    if evidence["inputs"]["images"][0]["sha256"] != hashlib.sha256(
        (images / "sony.png").read_bytes()
    ).hexdigest():
        raise AssertionError("provenance does not identify the decoded source image")
    run(base + ["--output", str(second)])
    if hashlib.sha256(first.read_bytes()).digest() != hashlib.sha256(second.read_bytes()).digest():
        raise AssertionError("identical texture bakes are not deterministic")
    if provenance.read_bytes() != pathlib.Path(str(second) + ".provenance.json").read_bytes():
        raise AssertionError("identical texture provenance is not deterministic")
    sentinel = root / "dry.glb"
    sentinel.write_bytes(b"preserve")
    run(base + ["--output", str(sentinel), "--dry-run"])
    if sentinel.read_bytes() != b"preserve":
        raise AssertionError("dry-run mutated its destination")
    rejected = json.loads(rig.read_text())
    rejected["accepted"] = False
    bad_rig = root / "rejected.json"
    bad_rig.write_text(json.dumps(rejected))
    failure = run(
        [str(executable), str(mesh), "--colmap", str(model), "--metric-rig", str(bad_rig),
         "--images", str(images), "--output", str(root / "bad.glb"), "--json"],
        expected=3,
    )
    if json.loads(failure.stderr)["ok"]:
        raise AssertionError("rejected rig did not produce a structured failure")
    print(json.dumps({"ok": True, "sha256": hashlib.sha256(first.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
