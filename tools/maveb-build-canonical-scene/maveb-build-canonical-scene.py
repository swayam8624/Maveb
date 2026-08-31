#!/usr/bin/env python3
import argparse
import hashlib
import json
import math
import shutil
import struct
import sys
from pathlib import Path

TYPE_INFO = {
    "char": ("b", int), "int8": ("b", int),
    "uchar": ("B", int), "uint8": ("B", int),
    "short": ("h", int), "int16": ("h", int),
    "ushort": ("H", int), "uint16": ("H", int),
    "int": ("i", int), "int32": ("i", int),
    "uint": ("I", int), "uint32": ("I", int),
    "float": ("f", float), "float32": ("f", float),
    "double": ("d", float), "float64": ("d", float),
}
FLOAT_TYPES = {"float", "float32", "double", "float64"}
C1 = 0.4886025119029199
C2 = (1.0925484305920792, -1.0925484305920792, 0.31539156525252005,
      -1.0925484305920792, 0.5462742152960396)
C3 = (-0.5900435899266435, 2.890611442640554, -0.4570457994644658,
      0.3731763325901154, -0.4570457994644658, 1.445305721320277,
      -0.5900435899266435)


class BuildError(RuntimeError):
    pass


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
                    encoding="utf-8")


def load_json(path, label):
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"Unable to read {label}: {path}: {exc}") from exc


def require(condition, message):
    if not condition:
        raise BuildError(message)


def finite_number(value, label):
    require(isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)), f"{label} must be finite")
    return float(value)


def normalize_quaternion(q, label="quaternion"):
    require(isinstance(q, list) and len(q) == 4, f"{label} must contain four values")
    values = [finite_number(v, label) for v in q]
    n = math.sqrt(sum(v * v for v in values))
    require(n > 1.0e-12, f"{label} is degenerate")
    values = [v / n for v in values]
    for value in values:
        if abs(value) > 1.0e-15:
            if value < 0.0:
                values = [-v for v in values]
            break
    return values


def quat_multiply(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return [
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    ]


def quat_matrix(q):
    w, x, y, z = q
    return [
        [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
        [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
        [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
    ]


def column_major_pose(q, t):
    r = quat_matrix(q)
    return [
        r[0][0], r[1][0], r[2][0], 0.0,
        r[0][1], r[1][1], r[2][1], 0.0,
        r[0][2], r[1][2], r[2][2], 0.0,
        t[0], t[1], t[2], 1.0,
    ]


def transpose(m):
    return [list(row) for row in zip(*m)]


def matvec(m, v):
    return [sum(a * b for a, b in zip(row, v)) for row in m]


def matmul(a, b):
    bt = transpose(b)
    return [[sum(x * y for x, y in zip(row, col)) for col in bt] for row in a]


def solve_matrix(a, b):
    n = len(a)
    require(n > 0 and all(len(row) == n for row in a), "Linear solve matrix is malformed")
    require(len(b) == n, "Linear solve right-hand side is malformed")
    m = len(b[0])
    require(all(len(row) == m for row in b), "Linear solve right-hand side is ragged")
    aug = [list(map(float, a[i])) + list(map(float, b[i])) for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(aug[row][col]))
        require(abs(aug[pivot][col]) > 1.0e-14, "SH rotation solve is singular")
        aug[col], aug[pivot] = aug[pivot], aug[col]
        scale = aug[col][col]
        aug[col] = [value / scale for value in aug[col]]
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            if factor == 0.0:
                continue
            aug[row] = [
                aug[row][index] - factor * aug[col][index]
                for index in range(n + m)
            ]
    return [row[n:] for row in aug]


def basis_l(degree, d):
    x, y, z = d
    if degree == 1:
        return [-C1 * y, C1 * z, -C1 * x]
    if degree == 2:
        xx, yy, zz = x * x, y * y, z * z
        return [
            C2[0] * x * y,
            C2[1] * y * z,
            C2[2] * (2.0 * zz - xx - yy),
            C2[3] * x * z,
            C2[4] * (xx - yy),
        ]
    if degree == 3:
        xx, yy, zz = x * x, y * y, z * z
        return [
            C3[0] * y * (3.0 * xx - yy),
            C3[1] * x * y * z,
            C3[2] * y * (4.0 * zz - xx - yy),
            C3[3] * z * (2.0 * zz - 3.0 * xx - 3.0 * yy),
            C3[4] * x * (4.0 * zz - xx - yy),
            C3[5] * z * (xx - yy),
            C3[6] * x * (xx - 3.0 * yy),
        ]
    raise BuildError(f"Unsupported SH degree: {degree}")


def fibonacci_directions(count=64):
    golden = (1.0 + math.sqrt(5.0)) / 2.0
    result = []
    for index in range(count):
        z = 1.0 - 2.0 * (index + 0.5) / count
        angle = 2.0 * math.pi * index / (golden * golden)
        radius = math.sqrt(max(0.0, 1.0 - z * z))
        result.append([radius * math.cos(angle), radius * math.sin(angle), z])
    return result


def sh_rotation_matrix(degree, world_rotation):
    directions = fibonacci_directions()
    source = [basis_l(degree, d) for d in directions]
    inverse_rotation = transpose(world_rotation)
    target = [basis_l(degree, matvec(inverse_rotation, d)) for d in directions]
    source_t = transpose(source)
    transform = solve_matrix(matmul(source_t, source), matmul(source_t, target))
    worst = 0.0
    for d in fibonacci_directions(29):
        old_d = matvec(inverse_rotation, d)
        expected = basis_l(degree, old_d)
        predicted = matvec(transpose(transform), basis_l(degree, d))
        worst = max(worst, max(abs(a - b) for a, b in zip(expected, predicted)))
    require(worst < 1.0e-10, f"SH degree-{degree} rotation validation failed ({worst})")
    return transform


def parse_ply_header(stream):
    first = stream.readline()
    require(first == b"ply\n" or first == b"ply\r\n", "Gaussian input is not a PLY file")
    fmt = None
    vertex_count = None
    properties = []
    current_element = None
    extra_nonempty_elements = []
    while True:
        raw = stream.readline()
        require(raw, "Gaussian PLY header is truncated")
        try:
            line = raw.decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise BuildError("Gaussian PLY header is not ASCII") from exc
        if not line or line.startswith("comment ") or line.startswith("obj_info "):
            continue
        parts = line.split()
        if parts[0] == "format":
            require(len(parts) == 3 and parts[2] == "1.0", "Gaussian PLY format is invalid")
            require(parts[1] in ("ascii", "binary_little_endian"),
                    "Gaussian PLY format must be ascii or binary_little_endian")
            require(fmt is None, "Gaussian PLY contains duplicate format declarations")
            fmt = parts[1]
        elif parts[0] == "element":
            require(len(parts) == 3, "Gaussian PLY element declaration is invalid")
            try:
                count = int(parts[2])
            except ValueError as exc:
                raise BuildError("Gaussian PLY element count is invalid") from exc
            require(count >= 0, "Gaussian PLY element count is negative")
            current_element = parts[1]
            if current_element == "vertex":
                require(vertex_count is None, "Gaussian PLY repeats the vertex element")
                vertex_count = count
            elif count:
                extra_nonempty_elements.append(current_element)
        elif parts[0] == "property":
            require(current_element == "vertex", "Gaussian PLY only supports scalar vertex properties")
            require(len(parts) == 3 and parts[1] != "list", "Gaussian PLY vertex property is invalid")
            require(parts[1] in TYPE_INFO, f"Unsupported Gaussian PLY scalar type: {parts[1]}")
            require(all(name != parts[2] for _, name in properties),
                    f"Duplicate Gaussian PLY property: {parts[2]}")
            properties.append((parts[1], parts[2]))
        elif parts[0] == "end_header":
            require(len(parts) == 1, "Gaussian PLY end_header is invalid")
            break
        else:
            raise BuildError(f"Unsupported Gaussian PLY header directive: {parts[0]}")
    require(fmt is not None and vertex_count is not None and vertex_count > 0,
            "Gaussian PLY header is incomplete")
    require(not extra_nonempty_elements,
            "Gaussian PLY contains unsupported non-vertex elements: " + ", ".join(extra_nonempty_elements))
    return fmt, vertex_count, properties


def gaussian_schema(properties):
    names = [name for _, name in properties]
    required = ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
                "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    for name in required:
        require(name in names, f"Gaussian PLY is missing required property: {name}")
    rest = sorted(
        int(name[len("f_rest_"):])
        for name in names
        if name.startswith("f_rest_") and name[len("f_rest_"):].isdigit()
    )
    if rest:
        require(rest == list(range(rest[-1] + 1)), "Gaussian SH properties are not dense")
        require(len(rest) == 45,
                "Canonical Gaussian rotation currently requires standard degree-3 GraphDECO SH (45 rest values)")
    property_types = {name: scalar_type for scalar_type, name in properties}
    for name in ["x", "y", "z", "scale_0", "scale_1", "scale_2",
                 "rot_0", "rot_1", "rot_2", "rot_3"] + [f"f_rest_{i}" for i in rest]:
        require(property_types[name] in FLOAT_TYPES,
                f"Gaussian transform property must be floating point: {name}")
    return names, len(rest)


def read_binary_record(stream, properties):
    fmt = "<" + "".join(TYPE_INFO[t][0] for t, _ in properties)
    size = struct.calcsize(fmt)
    data = stream.read(size)
    require(len(data) == size, "Gaussian PLY binary payload is truncated")
    return list(struct.unpack(fmt, data)), fmt


def read_ascii_record(stream, properties):
    line = stream.readline()
    require(line, "Gaussian PLY ASCII payload is truncated")
    try:
        tokens = line.decode("ascii").split()
    except UnicodeDecodeError as exc:
        raise BuildError("Gaussian PLY ASCII payload is not ASCII") from exc
    require(len(tokens) == len(properties), "Gaussian PLY ASCII record has the wrong field count")
    values = []
    for token, (scalar_type, name) in zip(tokens, properties):
        try:
            values.append(TYPE_INFO[scalar_type][1](token))
        except ValueError as exc:
            raise BuildError(f"Gaussian PLY field is invalid: {name}") from exc
    return values


def transform_gaussians(source, destination, transform):
    scale = finite_number(transform.get("scale"), "Alignment scale")
    require(scale > 0.0, "Alignment scale must be positive")
    orientation = normalize_quaternion(transform.get("orientationWxyz"), "Alignment orientation")
    translation = transform.get("translationMetres")
    require(isinstance(translation, list) and len(translation) == 3,
            "Alignment translationMetres must contain three values")
    translation = [finite_number(v, "Alignment translation") for v in translation]
    rotation = quat_matrix(orientation)
    sh_matrices = {degree: sh_rotation_matrix(degree, rotation) for degree in (1, 2, 3)}
    log_scale_delta = math.log(scale)

    with open(source, "rb") as input_stream:
        fmt, vertex_count, properties = parse_ply_header(input_stream)
        names, rest_count = gaussian_schema(properties)
        index = {name: i for i, name in enumerate(names)}
        output_header = ["ply", "format binary_little_endian 1.0",
                         "comment Canonicalized by maveb-build-canonical-scene",
                         f"element vertex {vertex_count}"]
        output_header.extend(f"property {t} {name}" for t, name in properties)
        output_header.append("end_header")
        record_fmt = "<" + "".join(TYPE_INFO[t][0] for t, _ in properties)
        with open(destination, "wb") as output_stream:
            output_stream.write(("\n".join(output_header) + "\n").encode("ascii"))
            for _ in range(vertex_count):
                values = (read_ascii_record(input_stream, properties)
                          if fmt == "ascii" else read_binary_record(input_stream, properties)[0])
                p = [float(values[index[axis]]) for axis in ("x", "y", "z")]
                p = matvec(rotation, p)
                p = [scale * p[i] + translation[i] for i in range(3)]
                for axis, value in zip(("x", "y", "z"), p):
                    values[index[axis]] = value
                q = normalize_quaternion(
                    [float(values[index[f"rot_{i}"]]) for i in range(4)], "Gaussian rotation")
                q = normalize_quaternion(quat_multiply(orientation, q),
                                         "Canonical Gaussian rotation")
                for i, value in enumerate(q):
                    values[index[f"rot_{i}"]] = value
                for i in range(3):
                    values[index[f"scale_{i}"]] = float(values[index[f"scale_{i}"]]) + log_scale_delta
                if rest_count == 45:
                    for channel in range(3):
                        base = channel * 15
                        for degree, begin, end in ((1, 0, 3), (2, 3, 8), (3, 8, 15)):
                            old = [float(values[index[f"f_rest_{base + i}"]]) for i in range(begin, end)]
                            new = matvec(sh_matrices[degree], old)
                            for offset, value in enumerate(new, begin):
                                values[index[f"f_rest_{base + offset}"]] = value
                try:
                    output_stream.write(struct.pack(record_fmt, *values))
                except (struct.error, OverflowError) as exc:
                    raise BuildError("Canonical Gaussian value cannot be represented by the source PLY scalar type") from exc
        trailing = input_stream.read(1)
        require(not trailing, "Gaussian PLY contains unexpected trailing payload")
    return {
        "count": vertex_count,
        "restCount": rest_count,
        "shDegree": 3 if rest_count == 45 else 0,
        "scale": scale,
        "orientationWxyz": orientation,
        "translationMetres": translation,
    }


def verify_glb(path):
    size = path.stat().st_size
    require(size >= 12, "Textured GLB is truncated")
    with open(path, "rb") as stream:
        header = stream.read(12)
    magic, version, declared = struct.unpack("<4sII", header)
    require(magic == b"glTF" and version == 2 and declared == size,
            "Textured GLB does not have a valid glTF 2 GLB header")


def capture_confidence(capture_root, manifest, matched_frame_ids):
    frames = manifest.get("frames")
    require(isinstance(frames, list) and frames, "Capture manifest has no frames")
    by_id = {}
    total = 0
    medium_or_high = 0
    per_frame = {}
    for frame in frames:
        frame_id = frame.get("frameID")
        require(isinstance(frame_id, int) and frame_id > 0 and frame_id not in by_id,
                "Capture frameID is invalid or repeated")
        by_id[frame_id] = frame
        confidence = frame.get("confidence")
        require(isinstance(confidence, dict), f"Capture frame {frame_id} has no confidence plane")
        relative = confidence.get("path")
        expected_sha = confidence.get("sha256")
        expected_bytes = confidence.get("byteCount")
        require(isinstance(relative, str) and relative and not Path(relative).is_absolute()
                and ".." not in Path(relative).parts,
                f"Capture confidence path is unsafe for frame {frame_id}")
        path = capture_root / relative
        data = path.read_bytes()
        require(isinstance(expected_bytes, int) and expected_bytes == len(data) and len(data) > 0,
                f"Capture confidence byte count mismatch for frame {frame_id}")
        require(isinstance(expected_sha, str) and sha256_bytes(data) == expected_sha,
                f"Capture confidence SHA-256 mismatch for frame {frame_id}")
        require(all(value in (0, 1, 2) for value in data),
                f"Capture confidence contains illegal codes for frame {frame_id}")
        accepted = sum(value >= 1 for value in data)
        total += len(data)
        medium_or_high += accepted
        if frame_id in matched_frame_ids:
            per_frame[frame_id] = accepted / len(data)
    require(total > 0, "Capture confidence is empty")
    require(set(matched_frame_ids) == set(per_frame),
            "Not every metric camera has a matched capture confidence plane")
    return by_id, medium_or_high / total, per_frame


def build_cameras(metric_rig, matches, capture_manifest, capture_frames, per_frame_confidence):
    source_id = capture_manifest.get("sourceID")
    require(isinstance(source_id, str) and source_id, "Capture sourceID is missing")
    pairs = matches.get("pairs")
    require(matches.get("schemaVersion") == 1 and isinstance(pairs, list) and pairs,
            "Camera matches must be schemaVersion 1 with pairs")
    image_to_frame = {}
    for pair in pairs:
        image = pair.get("colmapImage")
        frame_id = pair.get("captureFrameId")
        require(isinstance(image, str) and image and isinstance(frame_id, int) and frame_id > 0,
                "Camera match pair is malformed")
        require(image not in image_to_frame, "Camera matches repeat an image")
        image_to_frame[image] = frame_id
    metric = metric_rig.get("metricCameras")
    require(isinstance(metric, list) and metric, "Metric rig has no metricCameras")
    cameras = []
    local_flip = [0.0, 1.0, 0.0, 0.0]
    for camera in metric:
        image = camera.get("imageName")
        require(isinstance(image, str) and image in image_to_frame,
                f"Metric camera has no frozen frame correspondence: {image}")
        frame_id = image_to_frame[image]
        frame = capture_frames.get(frame_id)
        require(frame is not None, f"Capture frame is missing: {frame_id}")
        calibration = frame.get("calibration")
        require(isinstance(calibration, dict), f"Capture calibration is missing: {frame_id}")
        width, height = calibration.get("imageWidth"), calibration.get("imageHeight")
        intrinsics = calibration.get("imageIntrinsics")
        require(isinstance(width, int) and width > 0 and isinstance(height, int) and height > 0,
                f"Capture image dimensions are invalid: {frame_id}")
        require(isinstance(intrinsics, list) and len(intrinsics) == 9,
                f"Capture image intrinsics are invalid: {frame_id}")
        intrinsics = [finite_number(v, "Capture image intrinsic") for v in intrinsics]
        fx, fy, cx, cy = intrinsics[0], intrinsics[4], intrinsics[6], intrinsics[7]
        require(fx > 0.0 and fy > 0.0 and cx >= 0.0 and cy >= 0.0,
                f"Capture image intrinsics are invalid: {frame_id}")
        pose = camera.get("cameraToMetricWorld")
        require(isinstance(pose, dict), f"Metric camera pose is missing: {image}")
        q = normalize_quaternion(pose.get("orientationWxyz"), f"Metric camera orientation: {image}")
        t = pose.get("translation")
        require(isinstance(t, list) and len(t) == 3, f"Metric camera translation is invalid: {image}")
        t = [finite_number(v, "Metric camera translation") for v in t]
        q = normalize_quaternion(quat_multiply(q, local_flip),
                                 f"Canonical camera orientation: {image}")
        timestamp = frame.get("hostTimestampNanoseconds")
        require(isinstance(timestamp, int) and timestamp >= 0,
                f"Capture timestamp is invalid: {frame_id}")
        cameras.append({
            "id": f"capture-frame-{frame_id:06d}",
            "sourceId": source_id,
            "image": image,
            "width": width,
            "height": height,
            "intrinsics": [fx, fy, cx, cy],
            "cameraToWorld": column_major_pose(q, t),
            "timestampNanoseconds": timestamp,
            "confidence": per_frame_confidence[frame_id],
        })
    require(len(cameras) == len(image_to_frame),
            "Metric camera count does not match frozen camera correspondences")
    return {"schemaVersion": 1, "cameras": cameras}


def validate_provenance(args, capture_manifest_sha, proxy_sha, rig_sha, matches_sha, glb_sha):
    rig = load_json(args.metric_rig, "metric camera rig")
    require(rig.get("schemaVersion") == 1 and rig.get("accepted") is True,
            "Metric camera rig must be accepted schemaVersion 1")
    rig_provenance = rig.get("provenance")
    require(isinstance(rig_provenance, dict), "Metric camera rig provenance is missing")
    require(rig_provenance.get("captureManifestSha256") == capture_manifest_sha,
            "Metric camera rig does not reference the frozen capture manifest")
    require(rig_provenance.get("matchesSha256") == matches_sha,
            "Metric camera rig does not reference the supplied frozen camera matches")
    transform = rig.get("transform")
    require(isinstance(transform, dict), "Metric camera rig transform is missing")
    geometry = load_json(args.geometry_evidence, "metric proxy evidence")
    require(geometry.get("proxy", {}).get("sha256") == proxy_sha,
            "Metric proxy does not match frozen C1.3 evidence")
    require(geometry.get("input", {}).get("captureManifestSha256") == capture_manifest_sha,
            "Metric proxy evidence does not reference the frozen capture manifest")
    fusion = geometry.get("fusion")
    require(isinstance(fusion, dict), "Metric proxy fusion provenance is missing")
    texture = load_json(args.texture_provenance, "texture bake provenance")
    texture_inputs = texture.get("inputs")
    texture_config = texture.get("configuration")
    texture_result = texture.get("result")
    require(isinstance(texture_inputs, dict) and isinstance(texture_config, dict)
            and isinstance(texture_result, dict), "Texture bake provenance is incomplete")
    require(texture_inputs.get("meshSha256") == proxy_sha,
            "Texture bake provenance does not reference the metric proxy")
    require(texture_inputs.get("metricRigSha256") == rig_sha,
            "Texture bake provenance does not reference the metric camera rig")
    require(texture_result.get("glbSha256") == glb_sha,
            "Textured GLB does not match texture bake provenance")
    return rig, geometry, texture, transform


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Build a deterministic Canonical Asset v1 scene from frozen Maveb reference-world artifacts.")
    parser.add_argument("--proxy", required=True, type=Path, help="Frozen metric TSDF proxy PLY")
    parser.add_argument("--geometry-evidence", required=True, type=Path,
                        help="Frozen C1.3 metric-proxy evidence JSON")
    parser.add_argument("--textured-glb", required=True, type=Path,
                        help="Metric textured GLB produced by maveb-texture-bake")
    parser.add_argument("--texture-provenance", required=True, type=Path,
                        help="maveb-texture-bake provenance JSON")
    parser.add_argument("--gaussians", required=True, type=Path,
                        help="Brush base Gaussians in the COLMAP coordinate frame")
    parser.add_argument("--metric-rig", required=True, type=Path,
                        help="Accepted maveb-align-sensors metric camera rig")
    parser.add_argument("--capture", required=True, type=Path,
                        help="Frozen .mavebcapture directory")
    parser.add_argument("--camera-matches", required=True, type=Path,
                        help="Frozen schema-v1 image/frame correspondence JSON")
    parser.add_argument("--output", required=True, type=Path, help="Destination scene directory")
    parser.add_argument("--name", default="Maveb Reference World v1")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def run(argv):
    args = parse_args(argv)
    for path, label in [
        (args.proxy, "metric proxy"),
        (args.geometry_evidence, "metric proxy evidence"),
        (args.textured_glb, "textured GLB"),
        (args.texture_provenance, "texture provenance"),
        (args.gaussians, "base Gaussians"),
        (args.metric_rig, "metric camera rig"),
        (args.camera_matches, "camera matches"),
    ]:
        require(path.is_file(), f"{label} is missing: {path}")
    require(args.capture.is_dir(), f"Frozen capture directory is missing: {args.capture}")
    manifest_path = args.capture / "manifest.json"
    require(manifest_path.is_file(), f"Frozen capture manifest is missing: {manifest_path}")
    require(not args.output.exists(), f"Output already exists: {args.output}")
    temporary = args.output.with_name(args.output.name + ".tmp")
    require(not temporary.exists(), f"Temporary output already exists: {temporary}")
    verify_glb(args.textured_glb)
    capture_manifest_bytes = manifest_path.read_bytes()
    capture_manifest_sha = sha256_bytes(capture_manifest_bytes)
    capture_manifest = load_json(manifest_path, "capture manifest")
    require(capture_manifest.get("schemaVersion") == 2,
            "Canonical scene builder requires finalized schema-v2 MavebCapture input")
    matches_bytes = args.camera_matches.read_bytes()
    matches_sha = sha256_bytes(matches_bytes)
    matches = load_json(args.camera_matches, "camera matches")
    proxy_sha = sha256_file(args.proxy)
    rig_sha = sha256_file(args.metric_rig)
    glb_sha = sha256_file(args.textured_glb)
    gaussian_input_sha = sha256_file(args.gaussians)
    rig, geometry, texture, transform = validate_provenance(
        args, capture_manifest_sha, proxy_sha, rig_sha, matches_sha, glb_sha)
    matched_ids = {
        pair.get("captureFrameId") for pair in matches.get("pairs", [])
        if isinstance(pair, dict) and isinstance(pair.get("captureFrameId"), int)
    }
    capture_frames, global_confidence, per_frame_confidence = capture_confidence(
        args.capture, capture_manifest, matched_ids)
    cameras = build_cameras(rig, matches, capture_manifest, capture_frames, per_frame_confidence)
    temporary.mkdir(parents=True)
    try:
        shutil.copyfile(args.proxy, temporary / "proxy.ply")
        shutil.copyfile(args.textured_glb, temporary / "canonical.glb")
        gaussian_report = transform_gaussians(
            args.gaussians, temporary / "base-gaussians.ply", transform)
        write_json(temporary / "cameras.json", cameras)
        geometry_configuration_sha = sha256_bytes(canonical_json_bytes(geometry["fusion"]))
        appearance_input_sha = sha256_bytes(canonical_json_bytes(texture["inputs"]))
        appearance_configuration_sha = sha256_bytes(canonical_json_bytes(texture["configuration"]))
        manifest = {
            "schemaVersion": 1,
            "name": args.name,
            "coordinateSystem": "right-handed-y-up-negative-z-forward",
            "metersPerUnit": 1.0,
            "mesh": "canonical.glb",
            "cameras": "cameras.json",
            "confidence": {"kind": "uniform", "value": global_confidence},
            "geometryProvider": {
                "name": "aether-fuse",
                "version": "0.1.0",
                "inputSha256": capture_manifest_sha,
                "configurationSha256": geometry_configuration_sha,
            },
            "appearanceProvider": {
                "name": "maveb-texture-bake",
                "version": "0.1.0",
                "inputSha256": appearance_input_sha,
                "configurationSha256": appearance_configuration_sha,
            },
        }
        write_json(temporary / "canonical-asset.json", manifest)
        metadata = {
            "schemaVersion": 1,
            "name": args.name,
            "referenceWorldVersion": "v1",
            "sourceID": capture_manifest.get("sourceID"),
            "coordinateSystem": "right-handed-y-up-negative-z-forward",
            "metersPerUnit": 1.0,
            "representations": {
                "canonicalMesh": "canonical.glb",
                "metricProxy": "proxy.ply",
                "baseGaussians": "base-gaussians.ply",
            },
            "cameraCalibration": {
                "source": "MavebCapture schema-v2 recorded image intrinsics",
                "localAxisConversion": "+X right,+Y down,+Z forward -> +X right,+Y up,-Z forward",
            },
            "confidence": {
                "kind": "uniform-acquisition-summary",
                "value": global_confidence,
                "definition": "fraction of frozen capture confidence pixels with ARKit code >= medium",
                "cameraDefinition": "per-frame fraction of confidence pixels with ARKit code >= medium",
                "researchClaim": False,
            },
            "gaussianCanonicalization": {
                "source": "COLMAP/Brush reconstruction frame",
                "target": "metric capture world",
                "positionSim3Applied": True,
                "anisotropicRotationApplied": True,
                "logScaleAdjusted": True,
                "sphericalHarmonicsRotated": gaussian_report["shDegree"] == 3,
                "sphericalHarmonicBasis": "Maveb GraphDECO real SH through degree 3",
            },
            "provenance": "canonicalization.json",
        }
        write_json(temporary / "metadata.json", metadata)
        outputs = {
            "canonicalGlbSha256": sha256_file(temporary / "canonical.glb"),
            "proxyPlySha256": sha256_file(temporary / "proxy.ply"),
            "baseGaussiansPlySha256": sha256_file(temporary / "base-gaussians.ply"),
            "camerasJsonSha256": sha256_file(temporary / "cameras.json"),
            "canonicalAssetJsonSha256": sha256_file(temporary / "canonical-asset.json"),
            "metadataJsonSha256": sha256_file(temporary / "metadata.json"),
        }
        provenance = {
            "schemaVersion": 1,
            "generator": "maveb-build-canonical-scene",
            "coordinateContract": {
                "sourceGaussians": rig.get("coordinateContract", {}).get("source"),
                "metricRigTarget": rig.get("coordinateContract", {}).get("target"),
                "canonical": "right-handed Y-up metre world; camera local +X right +Y up -Z forward",
            },
            "inputs": {
                "captureManifestSha256": capture_manifest_sha,
                "cameraMatchesSha256": matches_sha,
                "metricRigSha256": rig_sha,
                "metricProxySha256": proxy_sha,
                "baseGaussiansSha256": gaussian_input_sha,
                "texturedGlbSha256": glb_sha,
                "geometryEvidenceSha256": sha256_file(args.geometry_evidence),
                "textureProvenanceSha256": sha256_file(args.texture_provenance),
            },
            "sim3": {
                "scale": gaussian_report["scale"],
                "orientationWxyz": gaussian_report["orientationWxyz"],
                "translationMetres": gaussian_report["translationMetres"],
            },
            "gaussians": {
                "count": gaussian_report["count"],
                "shDegree": gaussian_report["shDegree"],
                "covarianceTransform": "q'=q_sim3*q; logScale'=logScale+log(scale)",
                "shTransform": "per-degree real-SH basis rotation satisfying F'(R d)=F(d)",
            },
            "cameras": {
                "count": len(cameras["cameras"]),
                "calibrationSource": "frozen capture image intrinsics",
                "poseSource": "accepted metric rig",
                "localBasisConversion": "postmultiply camera rotation by diag(1,-1,-1)",
            },
            "confidence": {
                "uniformValue": global_confidence,
                "definition": "global fraction of frozen capture confidence pixels with ARKit code >= medium",
                "perCameraFromMatchedCaptureFrame": True,
                "researchClaim": False,
            },
            "outputs": outputs,
        }
        write_json(temporary / "canonicalization.json", provenance)
        outputs["canonicalizationJsonSha256"] = sha256_file(temporary / "canonicalization.json")
        temporary.rename(args.output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    result = {
        "ok": True,
        "output": str(args.output),
        "cameras": len(cameras["cameras"]),
        "gaussians": gaussian_report["count"],
        "shDegree": gaussian_report["shDegree"],
        "uniformConfidence": global_confidence,
        "outputs": outputs,
    }
    if args.json:
        print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
    else:
        print(f"Built Canonical Asset v1 scene with {result['cameras']} cameras and "
              f"{result['gaussians']} Gaussians at {args.output}")
    return 0


def main():
    try:
        return run(sys.argv[1:])
    except BuildError as exc:
        if "--json" in sys.argv[1:]:
            print(json.dumps({"ok": False, "error": {"code": "canonical-scene-error",
                                                     "message": str(exc)}},
                             sort_keys=True, separators=(",", ":")), file=sys.stderr)
        else:
            print(f"maveb-build-canonical-scene: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if "--json" in sys.argv[1:]:
            print(json.dumps({"ok": False, "error": {"code": "canonical-scene-io",
                                                     "message": str(exc)}},
                             sort_keys=True, separators=(",", ":")), file=sys.stderr)
        else:
            print(f"maveb-build-canonical-scene: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
