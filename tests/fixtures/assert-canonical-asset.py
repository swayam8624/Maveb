#!/usr/bin/env python3

import base64
import hashlib
import json
import pathlib
import shutil
import struct
import subprocess
import sys


def make_glb(external_uri: bool = False) -> bytes:
    positions = struct.pack("<9f", 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    texture_coordinates = struct.pack("<6f", 0.0, 0.0, 1.0, 0.0, 0.0, 1.0)
    indices = struct.pack("<3H", 0, 1, 2)
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nWQAAAAASUVORK5CYII="
    )
    binary = positions + texture_coordinates + indices
    binary += b"\0" * ((4 - len(binary) % 4) % 4)
    image_offset = len(binary)
    binary += png
    binary_length = len(binary)
    binary += b"\0" * ((4 - len(binary) % 4) % 4)

    document = {
        "asset": {"version": "2.0", "generator": "Maveb canonical fixture"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "TEXCOORD_0": 1},
                        "indices": 2,
                        "material": 0,
                    }
                ]
            }
        ],
        "buffers": [{"byteLength": binary_length}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(positions)},
            {
                "buffer": 0,
                "byteOffset": len(positions),
                "byteLength": len(texture_coordinates),
            },
            {
                "buffer": 0,
                "byteOffset": len(positions) + len(texture_coordinates),
                "byteLength": len(indices),
            },
            {
                "buffer": 0,
                "byteOffset": image_offset,
                "byteLength": len(png),
            },
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 3,
                "type": "VEC3",
                "min": [0.0, 0.0, 0.0],
                "max": [1.0, 1.0, 0.0],
            },
            {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC2"},
            {"bufferView": 2, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
        "images": [{"bufferView": 3, "mimeType": "image/png"}],
        "samplers": [{}],
        "textures": [{"sampler": 0, "source": 0}],
        "materials": [
            {"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}
        ],
    }
    if external_uri:
        document["buffers"][0]["uri"] = "outside.bin"
    json_bytes = json.dumps(document, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * ((4 - len(json_bytes) % 4) % 4)
    total = 12 + 8 + len(json_bytes) + 8 + len(binary)
    return (
        struct.pack("<III", 0x46546C67, 2, total)
        + struct.pack("<II", len(json_bytes), 0x4E4F534A)
        + json_bytes
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )


def run_json(arguments: list[str], expected: int = 0) -> dict:
    result = subprocess.run(arguments, capture_output=True, text=True, check=False)
    if result.returncode != expected:
        raise AssertionError(
            f"command returned {result.returncode}, expected {expected}: {arguments}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    payload = result.stdout if result.stdout.strip() else result.stderr
    return json.loads(payload)


def write_mismatched_confidence_package(source: pathlib.Path, destination: pathlib.Path) -> None:
    data = source.read_bytes()
    table_offset = struct.unpack_from("<Q", data, 16)[0]
    chunk_count = struct.unpack_from("<I", data, 24)[0]
    entries = []
    for index in range(chunk_count):
        entry = struct.unpack_from("<IIQQQ32s", data, table_offset + index * 64)
        chunk_type, flags, offset, stored_size, uncompressed_size, digest = entry
        stored = data[offset : offset + stored_size]
        if chunk_type == 14:
            stored = struct.pack(
                "<8sHHIQQ2f", b"AETHCF\0\0", 1, 0, 4, 2, 0, 0.5, 0.5
            )
            flags &= ~2
            uncompressed_size = len(stored)
            digest = hashlib.sha256(stored).digest()
        entries.append((chunk_type, flags, stored, uncompressed_size, digest))

    body = bytearray()
    rewritten_entries = []
    for chunk_type, flags, stored, uncompressed_size, digest in entries:
        body.extend(b"\0" * ((-len(body)) % 64))
        offset = 64 + len(body)
        body.extend(stored)
        rewritten_entries.append(
            (chunk_type, flags, offset, len(stored), uncompressed_size, digest)
        )
    body.extend(b"\0" * ((-len(body)) % 64))
    rewritten_table_offset = 64 + len(body)
    for entry in rewritten_entries:
        body.extend(struct.pack("<IIQQQ32s", *entry))
    header = struct.pack(
        "<8sHHIQII32s",
        b"AETHER\0\0",
        1,
        1,
        0,
        rewritten_table_offset,
        chunk_count,
        0,
        hashlib.sha256(body).digest(),
    )
    destination.write_bytes(header + body)


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("usage: assert-canonical-asset.py PACK INSPECT WORK")
    pack = pathlib.Path(sys.argv[1]).resolve()
    inspect = pathlib.Path(sys.argv[2]).resolve()
    work = pathlib.Path(sys.argv[3]).resolve()
    shutil.rmtree(work, ignore_errors=True)
    scene = work / "scene"
    scene.mkdir(parents=True)
    glb = make_glb()
    (scene / "canonical.glb").write_bytes(glb)
    (scene / "metadata.json").write_text('{"name":"canonical-fixture"}\n', encoding="utf-8")
    cameras = {
        "schemaVersion": 1,
        "cameras": [
            {
                "id": "sony-0001",
                "sourceId": "sony-a7v",
                "image": "sony/0001.jpg",
                "width": 1920,
                "height": 1080,
                "intrinsics": [1200.0, 1200.0, 960.0, 540.0],
                "cameraToWorld": [
                    1.0, 0.0, 0.0, 0.0,
                    0.0, 1.0, 0.0, 0.0,
                    0.0, 0.0, 1.0, 0.0,
                    0.0, 0.0, 0.0, 1.0,
                ],
                "timestampNanoseconds": 42,
                "confidence": 0.95,
            }
        ],
    }
    camera_text = json.dumps(cameras, indent=2) + "\n"
    (scene / "cameras.json").write_text(camera_text, encoding="utf-8")
    configuration_hash = hashlib.sha256(b"canonical-fixture-v1").hexdigest()
    manifest = {
        "schemaVersion": 1,
        "name": "Canonical textured triangle",
        "coordinateSystem": "right-handed-y-up-negative-z-forward",
        "metersPerUnit": 1.0,
        "mesh": "canonical.glb",
        "cameras": "cameras.json",
        "confidence": {"kind": "uniform", "value": 0.8},
        "geometryProvider": {
            "name": "fixture-geometry",
            "version": "1",
            "inputSha256": hashlib.sha256(glb).hexdigest(),
            "configurationSha256": configuration_hash,
        },
        "appearanceProvider": {
            "name": "fixture-texture",
            "version": "1",
            "inputSha256": hashlib.sha256(camera_text.encode("utf-8")).hexdigest(),
            "configurationSha256": configuration_hash,
        },
    }
    manifest_path = scene / "canonical-asset.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    package = work / "canonical.aether"
    packed = run_json([str(pack), str(scene), "--output", str(package), "--json"])
    assert packed["ok"] is True
    assert packed["canonical"] is True
    assert packed["canonicalVertices"] == 3
    assert packed["canonicalTriangles"] == 1
    assert packed["canonicalCameras"] == 1
    assert packed["canonicalMaterials"] == 2
    assert packed["canonicalImages"] == 1
    assert packed["chunks"] == 5

    second_package = work / "canonical-second.aether"
    run_json([str(pack), str(scene), "--output", str(second_package), "--json"])
    assert hashlib.sha256(package.read_bytes()).digest() == hashlib.sha256(
        second_package.read_bytes()
    ).digest()

    inspected = run_json([str(inspect), "--json", str(package)])
    assert inspected["packageVersion"] == "1.1"
    assert inspected["canonical"] is True
    assert inspected["canonicalAsset"]["name"] == "Canonical textured triangle"
    assert inspected["canonicalAsset"]["cameras"] == 1
    assert inspected["canonicalAsset"]["confidenceValues"] == 3
    assert {chunk["type"] for chunk in inspected["chunks"]} == {
        "metadata",
        "cameras",
        "canonical-asset",
        "canonical-mesh",
        "canonical-confidence",
    }

    malformed_package = work / "mismatched-confidence.aether"
    write_mismatched_confidence_package(package, malformed_package)
    semantic_rejection = subprocess.run(
        [str(inspect), "--json", str(malformed_package)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert semantic_rejection.returncode == 4
    assert "does not match" in semantic_rejection.stderr

    version_zero_package = work / "canonical-version-zero.aether"
    version_zero_bytes = bytearray(package.read_bytes())
    struct.pack_into("<H", version_zero_bytes, 10, 0)
    version_zero_package.write_bytes(version_zero_bytes)
    version_rejection = subprocess.run(
        [str(inspect), "--json", str(version_zero_package)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert version_rejection.returncode == 4
    assert "version 1.1" in version_rejection.stderr

    manifest["mesh"] = "../outside.glb"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    rejected = subprocess.run(
        [str(pack), str(scene), "--dry-run", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode != 0
    assert "traversal" in rejected.stderr

    outside = work / "outside.glb"
    outside.write_bytes(glb)
    link = scene / "linked.glb"
    link.symlink_to(outside)
    manifest["mesh"] = "linked.glb"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    escaped = subprocess.run(
        [str(pack), str(scene), "--dry-run", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert escaped.returncode != 0
    assert "symlink escapes" in escaped.stderr

    (scene / "external.glb").write_bytes(make_glb(external_uri=True))
    manifest["mesh"] = "external.glb"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    external = subprocess.run(
        [str(pack), str(scene), "--dry-run", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert external.returncode != 0
    assert "external URI" in external.stderr

    (scene / "confidence.bin").write_bytes(
        struct.pack("<8sHHIQQ2f", b"AETHCF\0\0", 1, 0, 4, 2, 0, 0.5, 0.5)
    )
    manifest["mesh"] = "canonical.glb"
    manifest["confidence"] = {"kind": "per-vertex", "file": "confidence.bin"}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    mismatched = subprocess.run(
        [str(pack), str(scene), "--dry-run", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert mismatched.returncode != 0
    assert "does not match" in mismatched.stderr
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
