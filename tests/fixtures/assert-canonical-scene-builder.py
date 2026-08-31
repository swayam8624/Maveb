#!/usr/bin/env python3
import base64
import hashlib
import json
import math
import pathlib
import shutil
import struct
import subprocess
import sys

C1 = 0.4886025119029199
C2 = (1.0925484305920792, -1.0925484305920792, 0.31539156525252005,
      -1.0925484305920792, 0.5462742152960396)
C3 = (-0.5900435899266435, 2.890611442640554, -0.4570457994644658,
      0.3731763325901154, -0.4570457994644658, 1.445305721320277,
      -0.5900435899266435)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def make_glb():
    positions = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    uv = struct.pack("<6f", 0, 0, 1, 0, 0, 1)
    indices = struct.pack("<3H", 0, 1, 2)
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nWQAAAAASUVORK5CYII=")
    binary = positions + uv + indices
    binary += b"\0" * ((4 - len(binary) % 4) % 4)
    image_offset = len(binary)
    binary += png
    binary_length = len(binary)
    binary += b"\0" * ((4 - len(binary) % 4) % 4)
    doc = {
        "asset": {"version": "2.0", "generator": "canonical-scene-builder-contract"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{
            "attributes": {"POSITION": 0, "TEXCOORD_0": 1},
            "indices": 2,
            "material": 0,
        }]}],
        "buffers": [{"byteLength": binary_length}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(positions)},
            {"buffer": 0, "byteOffset": len(positions), "byteLength": len(uv)},
            {"buffer": 0, "byteOffset": len(positions) + len(uv), "byteLength": len(indices)},
            {"buffer": 0, "byteOffset": image_offset, "byteLength": len(png)},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3",
             "min": [0, 0, 0], "max": [1, 1, 0]},
            {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC2"},
            {"bufferView": 2, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
        "images": [{"bufferView": 3, "mimeType": "image/png"}],
        "samplers": [{}],
        "textures": [{"sampler": 0, "source": 0}],
        "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
    }
    encoded = json.dumps(doc, separators=(",", ":")).encode()
    encoded += b" " * ((4 - len(encoded) % 4) % 4)
    total = 12 + 8 + len(encoded) + 8 + len(binary)
    return (struct.pack("<III", 0x46546C67, 2, total)
            + struct.pack("<II", len(encoded), 0x4E4F534A) + encoded
            + struct.pack("<II", len(binary), 0x004E4942) + binary)


def make_gaussian(path):
    props = (["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2"]
             + [f"f_rest_{i}" for i in range(45)]
             + ["opacity", "scale_0", "scale_1", "scale_2",
                "rot_0", "rot_1", "rot_2", "rot_3"])
    values = []
    for name in props:
        if name == "x":
            values.append(1.0)
        elif name.startswith("f_dc_"):
            values.append(0.1)
        elif name.startswith("f_rest_"):
            values.append((int(name.rsplit("_", 1)[1]) + 1) * 0.01)
        elif name == "rot_0":
            values.append(1.0)
        else:
            values.append(0.0)
    header = ["ply", "format binary_little_endian 1.0", "element vertex 1"]
    header += [f"property float {name}" for name in props]
    header += ["end_header"]
    path.write_bytes(("\n".join(header) + "\n").encode()
                     + struct.pack("<" + "f" * len(values), *values))
    return props, values


def read_gaussian(path):
    with path.open("rb") as stream:
        assert stream.readline() == b"ply\n"
        props = []
        while True:
            line = stream.readline().decode().strip()
            if line.startswith("property "):
                props.append(line.split()[2])
            if line == "end_header":
                break
        data = stream.read()
    values = struct.unpack("<" + "f" * len(props), data)
    return props, values


def matvec(m, v):
    return [sum(a * b for a, b in zip(row, v)) for row in m]


def basis(degree, d):
    x, y, z = d
    if degree == 1:
        return [-C1 * y, C1 * z, -C1 * x]
    if degree == 2:
        xx, yy, zz = x*x, y*y, z*z
        return [C2[0]*x*y, C2[1]*y*z, C2[2]*(2*zz-xx-yy),
                C2[3]*x*z, C2[4]*(xx-yy)]
    xx, yy, zz = x*x, y*y, z*z
    return [C3[0]*y*(3*xx-yy), C3[1]*x*y*z, C3[2]*y*(4*zz-xx-yy),
            C3[3]*z*(2*zz-3*xx-3*yy), C3[4]*x*(4*zz-xx-yy),
            C3[5]*z*(xx-yy), C3[6]*x*(xx-3*yy)]


def run_json(args, expected=0):
    completed = subprocess.run(args, capture_output=True, text=True, check=False)
    if completed.returncode != expected:
        raise AssertionError(
            f"command returned {completed.returncode}, expected {expected}: {args}\n"
            f"stdout={completed.stdout}\nstderr={completed.stderr}")
    payload = completed.stdout.strip() or completed.stderr.strip()
    return json.loads(payload)


def main():
    if len(sys.argv) != 5:
        raise SystemExit("usage: assert-canonical-scene-builder.py PYTHON BUILDER PACK WORK")
    python = pathlib.Path(sys.argv[1])
    builder = pathlib.Path(sys.argv[2])
    pack = pathlib.Path(sys.argv[3])
    work = pathlib.Path(sys.argv[4])
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)

    capture = work / "fixture.mavebcapture"
    (capture / "confidence").mkdir(parents=True)
    confidence = bytes([0, 1, 2, 2])
    confidence_path = capture / "confidence" / "000001.u8"
    confidence_path.write_bytes(confidence)
    capture_manifest = {
        "schemaVersion": 2,
        "sourceID": "canonical-builder-fixture",
        "frames": [{
            "frameID": 1,
            "hostTimestampNanoseconds": 42,
            "calibration": {
                "imageWidth": 1920,
                "imageHeight": 1080,
                "imageIntrinsics": [1200.0, 0, 0, 0, 1201.0, 0, 960.0, 540.0, 1.0],
            },
            "confidence": {
                "path": "confidence/000001.u8",
                "sha256": hashlib.sha256(confidence).hexdigest(),
                "byteCount": len(confidence),
            },
        }],
    }
    manifest_path = capture / "manifest.json"
    write_json(manifest_path, capture_manifest)

    matches = {"schemaVersion": 1,
               "pairs": [{"colmapImage": "frame-000001.png", "captureFrameId": 1}]}
    matches_path = work / "matches.json"
    write_json(matches_path, matches)

    angle = math.pi / 2.0
    q = [math.cos(angle / 2.0), 0.0, 0.0, math.sin(angle / 2.0)]
    rig = {
        "schemaVersion": 1,
        "accepted": True,
        "coordinateContract": {
            "source": "COLMAP arbitrary scale, camera axes +X right +Y down +Z forward",
            "target": "Maveb metric capture world, camera axes +X right +Y down +Z forward",
        },
        "provenance": {
            "captureManifestSha256": sha(manifest_path),
            "matchesSha256": sha(matches_path),
        },
        "transform": {"scale": 2.0, "orientationWxyz": q, "translationMetres": [1.0, 2.0, 3.0]},
        "metricCameras": [{
            "imageId": 1,
            "cameraId": 1,
            "imageName": "frame-000001.png",
            "cameraToMetricWorld": {
                "translation": [1.0, 2.0, 3.0],
                "orientationWxyz": [1.0, 0.0, 0.0, 0.0],
            },
        }],
    }
    rig_path = work / "metric-rig.json"
    write_json(rig_path, rig)

    proxy_path = work / "proxy.ply"
    proxy_path.write_text(
        "ply\nformat ascii 1.0\n"
        "element vertex 3\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property float nx\nproperty float ny\nproperty float nz\n"
        "element face 1\nproperty list uchar uint vertex_indices\nend_header\n"
        "0 0 0 0 0 1\n1 0 0 0 0 1\n0 1 0 0 0 1\n3 0 1 2\n",
        encoding="ascii")
    geometry_path = work / "geometry.json"
    write_json(geometry_path, {
        "proxy": {"sha256": sha(proxy_path)},
        "input": {"captureManifestSha256": sha(manifest_path)},
        "fusion": {"tool": "aether-fuse", "requested": {"minimumVoxelMetres": 0.01}},
    })

    glb_path = work / "textured.glb"
    glb_path.write_bytes(make_glb())
    texture_path = work / "textured.glb.provenance.json"
    write_json(texture_path, {
        "schemaVersion": 1,
        "inputs": {
            "meshSha256": sha(proxy_path),
            "metricRigSha256": sha(rig_path),
            "images": [{"name": "frame-000001.png", "sha256": "0" * 64}],
        },
        "configuration": {"atlasSize": 4096, "visibilityWidth": 512, "visibilityHeight": 512},
        "result": {"glbSha256": sha(glb_path)},
    })

    gaussian_path = work / "base-source.ply"
    input_props, input_values = make_gaussian(gaussian_path)

    def build(output):
        return run_json([
            str(python), str(builder),
            "--proxy", str(proxy_path),
            "--geometry-evidence", str(geometry_path),
            "--textured-glb", str(glb_path),
            "--texture-provenance", str(texture_path),
            "--gaussians", str(gaussian_path),
            "--metric-rig", str(rig_path),
            "--capture", str(capture),
            "--camera-matches", str(matches_path),
            "--output", str(output),
            "--name", "Canonical builder fixture",
            "--json",
        ])

    scene_a, scene_b = work / "scene-a", work / "scene-b"
    result_a = build(scene_a)
    result_b = build(scene_b)
    assert result_a["cameras"] == result_b["cameras"] == 1
    assert result_a["gaussians"] == result_b["gaussians"] == 1
    assert result_a["shDegree"] == result_b["shDegree"] == 3
    assert result_a["uniformConfidence"] == result_b["uniformConfidence"] == 0.75
    files_a = sorted(path.name for path in scene_a.iterdir())
    files_b = sorted(path.name for path in scene_b.iterdir())
    assert files_a == files_b
    assert files_a == [
        "base-gaussians.ply", "cameras.json", "canonical-asset.json",
        "canonical.glb", "canonicalization.json", "metadata.json", "proxy.ply",
    ]
    for name in files_a:
        assert (scene_a / name).read_bytes() == (scene_b / name).read_bytes(), name

    props, values = read_gaussian(scene_a / "base-gaussians.ply")
    index = {name: i for i, name in enumerate(props)}
    transformed_position = [values[index[name]] for name in ("x", "y", "z")]
    assert max(abs(a - b) for a, b in zip(transformed_position, [1.0, 4.0, 3.0])) < 1e-6
    expected_q = [math.sqrt(0.5), 0.0, 0.0, math.sqrt(0.5)]
    transformed_q = [values[index[f"rot_{i}"]] for i in range(4)]
    assert max(abs(a - b) for a, b in zip(transformed_q, expected_q)) < 1e-6
    for i in range(3):
        assert abs(values[index[f"scale_{i}"]] - math.log(2.0)) < 1e-6

    rotation = [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]
    directions = [[1, 0, 0], [0, 1, 0], [0, 0, 1],
                  [1/math.sqrt(3)] * 3, [-0.6, 0.0, 0.8]]
    for channel in range(3):
        old = [input_values[input_props.index(f"f_rest_{channel*15+i}")] for i in range(15)]
        new = [values[index[f"f_rest_{channel*15+i}"]] for i in range(15)]
        for direction in directions:
            rotated = matvec(rotation, direction)
            for degree, begin, end in ((1, 0, 3), (2, 3, 8), (3, 8, 15)):
                expected = sum(c*b for c, b in zip(old[begin:end], basis(degree, direction)))
                actual = sum(c*b for c, b in zip(new[begin:end], basis(degree, rotated)))
                assert abs(expected - actual) < 1e-6

    cameras = json.loads((scene_a / "cameras.json").read_text())
    camera = cameras["cameras"][0]
    assert camera["intrinsics"] == [1200.0, 1201.0, 960.0, 540.0]
    assert camera["confidence"] == 0.75
    assert camera["cameraToWorld"] == [
        1.0, 0.0, 0.0, 0.0,
        0.0, -1.0, 0.0, 0.0,
        0.0, 0.0, -1.0, 0.0,
        1.0, 2.0, 3.0, 1.0,
    ]
    metadata = json.loads((scene_a / "metadata.json").read_text())
    assert metadata["confidence"]["researchClaim"] is False
    assert metadata["gaussianCanonicalization"]["sphericalHarmonicsRotated"] is True

    package = work / "fixture.aether"
    packed = run_json([str(pack), str(scene_a), "--output", str(package), "--json"])
    assert packed["ok"] is True
    assert packed["canonical"] is True
    assert packed["chunks"] == 7
    assert packed["canonicalVertices"] == 3
    assert packed["canonicalTriangles"] == 1
    assert packed["canonicalCameras"] == 1
    assert packed["canonicalMaterials"] == 2
    assert packed["canonicalImages"] == 1

    duplicate = subprocess.run([
        str(python), str(builder),
        "--proxy", str(proxy_path),
        "--geometry-evidence", str(geometry_path),
        "--textured-glb", str(glb_path),
        "--texture-provenance", str(texture_path),
        "--gaussians", str(gaussian_path),
        "--metric-rig", str(rig_path),
        "--capture", str(capture),
        "--camera-matches", str(matches_path),
        "--output", str(scene_a),
        "--json",
    ], capture_output=True, text=True, check=False)
    assert duplicate.returncode != 0
    assert "Output already exists" in duplicate.stderr
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
