#!/usr/bin/env python3
"""Exercise the native GLB CLI as a deterministic black-box contract."""

from __future__ import annotations

import hashlib
import json
import pathlib
import struct
import subprocess
import sys


def run(*arguments: str, expect_success: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(arguments, capture_output=True, check=False, text=True)
    if expect_success and result.returncode != 0:
        raise AssertionError(
            f"command failed ({result.returncode}): {' '.join(arguments)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    if not expect_success and result.returncode == 0:
        raise AssertionError(f"command unexpectedly succeeded: {' '.join(arguments)}")
    return result


def parse_glb(path: pathlib.Path) -> tuple[dict[str, object], bytes]:
    payload = path.read_bytes()
    if len(payload) < 20:
        raise AssertionError("GLB is shorter than its header and JSON chunk")
    magic, version, total_length = struct.unpack_from("<4sII", payload)
    if magic != b"glTF" or version != 2 or total_length != len(payload):
        raise AssertionError("GLB header is invalid")
    json_length, json_type = struct.unpack_from("<II", payload, 12)
    if json_type != 0x4E4F534A:
        raise AssertionError("GLB does not start with a JSON chunk")
    json_end = 20 + json_length
    document = json.loads(payload[20:json_end].decode("utf-8").rstrip(" \x00"))
    binary_length, binary_type = struct.unpack_from("<II", payload, json_end)
    if binary_type != 0x004E4942:
        raise AssertionError("GLB does not contain a BIN chunk")
    binary = payload[json_end + 8 : json_end + 8 + binary_length]
    if len(binary) != binary_length:
        raise AssertionError("GLB BIN chunk is truncated")
    return document, binary


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("usage: assert-native-glb.py <cli> <fixtures> <artifact-directory>")
    executable = pathlib.Path(sys.argv[1])
    fixtures = pathlib.Path(sys.argv[2])
    artifacts = pathlib.Path(sys.argv[3])
    artifacts.mkdir(parents=True, exist_ok=True)

    first = artifacts / "native-first.glb"
    second = artifacts / "native-second.glb"
    for output in (first, second):
        output.unlink(missing_ok=True)

    first_result = run(
        str(executable),
        str(fixtures / "textured-triangle.gltf"),
        "--output",
        str(first),
        "--json",
    )
    report = json.loads(first_result.stdout)
    assert report["ok"] is True
    assert report["dryRun"] is False
    assert report["vertices"] == 3
    assert report["triangles"] == 1
    assert report["images"] == 1
    assert report["sha256"] == hashlib.sha256(first.read_bytes()).hexdigest()

    run(
        str(executable),
        str(fixtures / "textured-triangle.gltf"),
        "--output",
        str(second),
        "--json",
    )
    assert first.read_bytes() == second.read_bytes()

    document, binary = parse_glb(first)
    assert document["asset"]["version"] == "2.0"
    assert "uri" not in document["buffers"][0]
    assert all("uri" not in image for image in document["images"])
    assert all("bufferView" in image for image in document["images"])
    assert "KHR_texture_transform" in document["extensionsUsed"]
    attributes = document["meshes"][0]["primitives"][0]["attributes"]
    assert "POSITION" in attributes
    assert "NORMAL" in attributes
    assert "TANGENT" in attributes
    assert "TEXCOORD_0" in attributes
    assert len(binary) > 0

    sentinel = artifacts / "dry-run-destination.glb"
    sentinel.write_bytes(b"must remain unchanged")
    dry_result = run(
        str(executable),
        str(fixtures / "textured-triangle.gltf"),
        "--output",
        str(sentinel),
        "--dry-run",
        "--json",
    )
    assert json.loads(dry_result.stdout)["dryRun"] is True
    assert sentinel.read_bytes() == b"must remain unchanged"
    assert not pathlib.Path(f"{sentinel}.dry-run.tmp.glb").exists()

    rejected = artifacts / "must-not-exist.glb"
    rejected.unlink(missing_ok=True)
    rejection = run(
        str(executable),
        str(fixtures / "animated-triangle.gltf"),
        "--output",
        str(rejected),
        "--json",
        expect_success=False,
    )
    error = json.loads(rejection.stderr)
    assert error["ok"] is False
    assert "animation" in error["error"]["message"].lower()
    assert not rejected.exists()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
