#!/usr/bin/env python3
"""Build deterministic canonical proxy meshes from dataset-native geometry/depth+pose.

This helper exists specifically for broad CBRC world preparation. It does not run
SfM and it never estimates camera motion from RGB. Instead it uses:
- 3RScan's provided reference mesh;
- ARKitScenes' provided registered depth, intrinsics, and trajectory;
- Bonn RGB-D's provided registered depth and ground-truth camera trajectory.

The resulting proxy is canonicalized to the same 2 m scene diagonal convention
used by the broad benchmark's other seeded representations. The source metric
scale and the canonicalization transform are recorded in a JSON sidecar.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import shutil
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

AR_KIT_POSE_TOLERANCE = 0.0051
AR_KIT_ASSET_TOLERANCE = 0.0011
BONN_ASSOCIATION_TOLERANCE = 0.05


@dataclass
class Mesh:
    vertices: list[tuple[float, float, float, int, int, int]]
    faces: list[tuple[int, int, int]]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def overlap_preserving_indices(count: int, maximum: int, maximum_stride: int = 8) -> list[int]:
    if count <= 0:
        return []
    if maximum <= 0 or count <= maximum:
        return list(range(count))
    if maximum == 1:
        return [count // 2]
    stride = max(1, min(maximum_stride, (count - 1) // (maximum - 1)))
    span = stride * (maximum - 1)
    start = max(0, (count - 1 - span) // 2)
    return [start + index * stride for index in range(maximum)]


def nearest_timestamp(target: float, values: list[float], tolerance: float) -> float | None:
    index = bisect.bisect_left(values, target)
    candidates: list[float] = []
    if index < len(values):
        candidates.append(values[index])
    if index:
        candidates.append(values[index - 1])
    if not candidates:
        return None
    best = min(candidates, key=lambda value: abs(value - target))
    return best if abs(best - target) <= tolerance else None


def timestamp_from_path(path: Path) -> float:
    try:
        return float(path.stem.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        try:
            return float(path.stem)
        except ValueError as exc:
            raise ValueError(f"cannot parse timestamp from {path.name}") from exc


def timestamp_index(paths: Iterable[Path]) -> tuple[list[float], dict[float, Path]]:
    mapping = {timestamp_from_path(path): path for path in paths}
    return sorted(mapping), mapping


def rodrigues(vector: tuple[float, float, float]) -> list[list[float]]:
    x, y, z = vector
    theta = math.sqrt(x * x + y * y + z * z)
    if theta < 1.0e-12:
        return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    x, y, z = x / theta, y / theta, z / theta
    cosine = math.cos(theta)
    sine = math.sin(theta)
    q = 1.0 - cosine
    return [
        [x * x * q + cosine, x * y * q - z * sine, x * z * q + y * sine],
        [y * x * q + z * sine, y * y * q + cosine, y * z * q - x * sine],
        [z * x * q - y * sine, z * y * q + x * sine, z * z * q + cosine],
    ]


def arkit_image_camera_to_world(tokens: list[float]) -> tuple[list[list[float]], tuple[float, float, float]]:
    if len(tokens) != 7:
        raise ValueError("ARKit trajectory rows require seven values")
    rotation = rodrigues((tokens[1], tokens[2], tokens[3]))
    transpose = [[rotation[column][row] for column in range(3)] for row in range(3)]
    translation = tokens[4:7]
    position = tuple(
        -sum(transpose[row][column] * translation[column] for column in range(3))
        for row in range(3)
    )
    return transpose, position


def load_arkit_trajectory(path: Path) -> tuple[list[float], dict[float, tuple[list[list[float]], tuple[float, float, float]]]]:
    poses: dict[float, tuple[list[list[float]], tuple[float, float, float]]] = {}
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            values = [float(value) for value in line.split()]
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: invalid trajectory row") from exc
        if len(values) != 7:
            raise ValueError(f"{path}:{line_number}: expected seven fields")
        poses[values[0]] = arkit_image_camera_to_world(values)
    if not poses:
        raise ValueError(f"no poses in {path}")
    return sorted(poses), poses


def quaternion_matrix(x: float, y: float, z: float, w: float) -> list[list[float]]:
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if not math.isfinite(norm) or norm < 1.0e-12:
        raise ValueError("degenerate quaternion")
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]


def transform(
    rotation: list[list[float]],
    translation: tuple[float, float, float],
    point: tuple[float, float, float],
) -> tuple[float, float, float]:
    return tuple(
        translation[row] + sum(rotation[row][column] * point[column] for column in range(3))
        for row in range(3)
    )


def read_intrinsics(path: Path) -> tuple[int, int, float, float, float, float]:
    values = path.read_text().strip().split()
    if len(values) != 6:
        raise ValueError(f"invalid ARKitScenes .pincam: {path}")
    width, height, fx, fy, cx, cy = map(float, values)
    if width <= 0 or height <= 0 or fx <= 0 or fy <= 0:
        raise ValueError(f"invalid calibration: {path}")
    return int(width), int(height), fx, fy, cx, cy


def ffmpeg_decode(ffmpeg: str, source: Path, pixel_format: str) -> bytes:
    process = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            pixel_format,
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode:
        raise RuntimeError(process.stderr.decode(errors="replace").strip())
    return process.stdout


def add_depth_frame(
    mesh: Mesh,
    *,
    depth_raw: bytes,
    rgb_raw: bytes,
    width: int,
    height: int,
    fx: float,
    fy: float,
    cx: float,
    cy: float,
    depth_scale: float,
    rotation: list[list[float]],
    translation: tuple[float, float, float],
    pixel_stride: int,
    maximum_depth: float,
) -> tuple[int, int]:
    expected_depth = width * height * 2
    expected_rgb = width * height * 3
    if len(depth_raw) != expected_depth:
        raise ValueError(f"depth byte count mismatch: {len(depth_raw)} != {expected_depth}")
    if len(rgb_raw) != expected_rgb:
        raise ValueError(f"RGB byte count mismatch: {len(rgb_raw)} != {expected_rgb}")

    rows = list(range(0, height, pixel_stride))
    columns = list(range(0, width, pixel_stride))
    grid: list[list[int | None]] = [[None for _ in columns] for _ in rows]
    depth_grid: list[list[float | None]] = [[None for _ in columns] for _ in rows]
    before_vertices = len(mesh.vertices)
    before_faces = len(mesh.faces)

    for row_index, v in enumerate(rows):
        for column_index, u in enumerate(columns):
            raw_depth = struct.unpack_from("<H", depth_raw, 2 * (v * width + u))[0]
            depth = raw_depth * depth_scale
            if raw_depth == 0 or not math.isfinite(depth) or depth <= 0.05 or depth > maximum_depth:
                continue
            local = (
                (u - cx) * depth / fx,
                (v - cy) * depth / fy,
                depth,
            )
            world = transform(rotation, translation, local)
            if not all(math.isfinite(value) and abs(value) < 1.0e6 for value in world):
                continue
            rgb_offset = 3 * (v * width + u)
            red, green, blue = rgb_raw[rgb_offset : rgb_offset + 3]
            index = len(mesh.vertices)
            mesh.vertices.append((world[0], world[1], world[2], red, green, blue))
            grid[row_index][column_index] = index
            depth_grid[row_index][column_index] = depth

    def valid_triangle(points: tuple[tuple[int, int], tuple[int, int], tuple[int, int]]) -> tuple[int, int, int] | None:
        indices: list[int] = []
        depths: list[float] = []
        for row, column in points:
            index = grid[row][column]
            depth = depth_grid[row][column]
            if index is None or depth is None:
                return None
            indices.append(index)
            depths.append(depth)
        maximum = max(depths)
        minimum = min(depths)
        # Faces are only a proxy-loader contract; reject obvious depth-edge bridges.
        if maximum - minimum > max(0.08, 0.08 * maximum):
            return None
        if len(set(indices)) != 3:
            return None
        return indices[0], indices[1], indices[2]

    for row in range(len(rows) - 1):
        for column in range(len(columns) - 1):
            for triangle in (
                ((row, column), (row, column + 1), (row + 1, column)),
                ((row, column + 1), (row + 1, column + 1), (row + 1, column)),
            ):
                face = valid_triangle(triangle)
                if face is not None:
                    mesh.faces.append(face)

    return len(mesh.vertices) - before_vertices, len(mesh.faces) - before_faces


def parse_manifest(path: Path) -> list[tuple[float, Path]]:
    rows: list[tuple[float, Path]] = []
    root = path.parent
    for line_number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split()
        if len(fields) < 2:
            raise ValueError(f"{path}:{line_number}: malformed manifest row")
        try:
            timestamp = float(fields[0])
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: invalid timestamp") from exc
        item = root / fields[1]
        if item.is_file():
            rows.append((timestamp, item))
    return rows


def parse_groundtruth(path: Path) -> tuple[list[float], dict[float, tuple[list[list[float]], tuple[float, float, float]]]]:
    poses: dict[float, tuple[list[list[float]], tuple[float, float, float]]] = {}
    for line_number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split()
        if len(fields) < 8:
            raise ValueError(f"{path}:{line_number}: malformed ground-truth row")
        try:
            timestamp, tx, ty, tz, qx, qy, qz, qw = map(float, fields[:8])
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: invalid numeric value") from exc
        poses[timestamp] = (quaternion_matrix(qx, qy, qz, qw), (tx, ty, tz))
    if not poses:
        raise ValueError(f"no ground-truth poses in {path}")
    return sorted(poses), poses


def obj_mesh(path: Path) -> Mesh:
    positions: list[tuple[float, float, float, int, int, int]] = []
    faces: list[tuple[int, int, int]] = []
    for line_number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split()
        if fields[0] == "v" and len(fields) >= 4:
            try:
                x, y, z = map(float, fields[1:4])
            except ValueError as exc:
                raise ValueError(f"{path}:{line_number}: invalid vertex") from exc
            if len(fields) >= 7:
                try:
                    raw = [float(value) for value in fields[4:7]]
                    if max(raw) <= 1.0:
                        color = tuple(max(0, min(255, round(value * 255.0))) for value in raw)
                    else:
                        color = tuple(max(0, min(255, round(value))) for value in raw)
                except ValueError:
                    color = (180, 180, 180)
            else:
                color = (180, 180, 180)
            positions.append((x, y, z, color[0], color[1], color[2]))
        elif fields[0] == "f" and len(fields) >= 4:
            indices: list[int] = []
            for token in fields[1:]:
                raw = token.split("/", 1)[0]
                try:
                    index = int(raw)
                except ValueError as exc:
                    raise ValueError(f"{path}:{line_number}: invalid face index") from exc
                if index < 0:
                    index = len(positions) + index
                else:
                    index -= 1
                if index < 0 or index >= len(positions):
                    raise ValueError(f"{path}:{line_number}: face index out of range")
                indices.append(index)
            for offset in range(1, len(indices) - 1):
                triangle = (indices[0], indices[offset], indices[offset + 1])
                if len(set(triangle)) == 3:
                    faces.append(triangle)
    if len(positions) < 3 or not faces:
        raise ValueError(f"{path} did not contain a usable triangle mesh")
    return Mesh(positions, faces)


def build_arkit(source: Path, maximum_frames: int, maximum_vertices: int, ffmpeg: str) -> tuple[Mesh, dict]:
    trajectory = source / "lowres_wide.traj"
    rgb_dir = source / "lowres_wide"
    depth_dir = source / "lowres_depth"
    intrinsics_dir = source / "lowres_wide_intrinsics"
    for required in (trajectory, rgb_dir, depth_dir, intrinsics_dir):
        if not required.exists():
            raise ValueError(f"missing ARKitScenes asset: {required}")

    pose_times, poses = load_arkit_trajectory(trajectory)
    rgb_times, rgbs = timestamp_index(rgb_dir.glob("*.png"))
    depth_times, depths = timestamp_index(depth_dir.glob("*.png"))
    intr_times, intrinsics = timestamp_index(intrinsics_dir.glob("*.pincam"))
    selected_times = [depth_times[index] for index in overlap_preserving_indices(len(depth_times), maximum_frames)]
    if not selected_times:
        raise ValueError("no ARKitScenes depth frames")

    first_intr_timestamp = nearest_timestamp(selected_times[0], intr_times, AR_KIT_ASSET_TOLERANCE)
    if first_intr_timestamp is None:
        raise ValueError("no ARKitScenes intrinsics matched the selected depth frames")
    width, height, *_ = read_intrinsics(intrinsics[first_intr_timestamp])
    pixel_stride = max(
        1,
        math.ceil(math.sqrt((width * height * max(len(selected_times), 1)) / maximum_vertices)),
    )

    mesh = Mesh([], [])
    converted = 0
    skipped = {"rgb": 0, "intrinsics": 0, "pose": 0, "decode": 0, "empty": 0}
    selected_provenance: list[float] = []
    for timestamp in selected_times:
        rgb_timestamp = nearest_timestamp(timestamp, rgb_times, AR_KIT_ASSET_TOLERANCE)
        intr_timestamp = nearest_timestamp(timestamp, intr_times, AR_KIT_ASSET_TOLERANCE)
        pose_timestamp = nearest_timestamp(timestamp, pose_times, AR_KIT_POSE_TOLERANCE)
        if rgb_timestamp is None:
            skipped["rgb"] += 1
            continue
        if intr_timestamp is None:
            skipped["intrinsics"] += 1
            continue
        if pose_timestamp is None:
            skipped["pose"] += 1
            continue
        width, height, fx, fy, cx, cy = read_intrinsics(intrinsics[intr_timestamp])
        try:
            depth_raw = ffmpeg_decode(ffmpeg, depths[timestamp], "gray16le")
            rgb_raw = ffmpeg_decode(ffmpeg, rgbs[rgb_timestamp], "rgb24")
        except RuntimeError:
            skipped["decode"] += 1
            continue
        before = len(mesh.vertices)
        add_depth_frame(
            mesh,
            depth_raw=depth_raw,
            rgb_raw=rgb_raw,
            width=width,
            height=height,
            fx=fx,
            fy=fy,
            cx=cx,
            cy=cy,
            depth_scale=0.001,
            rotation=poses[pose_timestamp][0],
            translation=poses[pose_timestamp][1],
            pixel_stride=pixel_stride,
            maximum_depth=10.0,
        )
        if len(mesh.vertices) == before:
            skipped["empty"] += 1
            continue
        converted += 1
        selected_provenance.append(timestamp)

    if converted < 2 or len(mesh.vertices) < 64 or not mesh.faces:
        raise ValueError(
            f"ARKitScenes native fusion is too sparse: frames={converted} "
            f"vertices={len(mesh.vertices)} faces={len(mesh.faces)}"
        )
    return mesh, {
        "sourceRepresentation": "arkitscenes-registered-depth-plus-provided-trajectory",
        "candidateFrames": len(selected_times),
        "convertedFrames": converted,
        "selectedDepthTimestamps": selected_provenance,
        "pixelStride": pixel_stride,
        "skipped": skipped,
    }


def build_bonn(
    source: Path,
    maximum_frames: int,
    maximum_vertices: int,
    ffmpeg: str,
    width: int,
    height: int,
    fx: float,
    fy: float,
    cx: float,
    cy: float,
) -> tuple[Mesh, dict]:
    rgb_rows = parse_manifest(source / "rgb.txt")
    depth_rows = parse_manifest(source / "depth.txt")
    pose_times, poses = parse_groundtruth(source / "groundtruth.txt")
    if not rgb_rows or not depth_rows:
        raise ValueError("Bonn sequence is missing usable RGB/depth manifest rows")

    rgb_times = [timestamp for timestamp, _ in rgb_rows]
    rgb_map = dict(rgb_rows)
    selected = [depth_rows[index] for index in overlap_preserving_indices(len(depth_rows), maximum_frames)]
    pixel_stride = max(
        1,
        math.ceil(math.sqrt((width * height * max(len(selected), 1)) / maximum_vertices)),
    )

    mesh = Mesh([], [])
    converted = 0
    skipped = {"rgb": 0, "pose": 0, "decode": 0, "empty": 0}
    selected_provenance: list[float] = []
    for timestamp, depth_path in selected:
        rgb_timestamp = nearest_timestamp(timestamp, rgb_times, BONN_ASSOCIATION_TOLERANCE)
        pose_timestamp = nearest_timestamp(timestamp, pose_times, BONN_ASSOCIATION_TOLERANCE)
        if rgb_timestamp is None:
            skipped["rgb"] += 1
            continue
        if pose_timestamp is None:
            skipped["pose"] += 1
            continue
        try:
            depth_raw = ffmpeg_decode(ffmpeg, depth_path, "gray16le")
            rgb_raw = ffmpeg_decode(ffmpeg, rgb_map[rgb_timestamp], "rgb24")
        except RuntimeError:
            skipped["decode"] += 1
            continue
        before = len(mesh.vertices)
        add_depth_frame(
            mesh,
            depth_raw=depth_raw,
            rgb_raw=rgb_raw,
            width=width,
            height=height,
            fx=fx,
            fy=fy,
            cx=cx,
            cy=cy,
            depth_scale=1.0 / 5000.0,
            rotation=poses[pose_timestamp][0],
            translation=poses[pose_timestamp][1],
            pixel_stride=pixel_stride,
            maximum_depth=10.0,
        )
        if len(mesh.vertices) == before:
            skipped["empty"] += 1
            continue
        converted += 1
        selected_provenance.append(timestamp)

    if converted < 2 or len(mesh.vertices) < 64 or not mesh.faces:
        raise ValueError(
            f"Bonn native fusion is too sparse: frames={converted} "
            f"vertices={len(mesh.vertices)} faces={len(mesh.faces)}"
        )
    return mesh, {
        "sourceRepresentation": "bonn-registered-depth-plus-groundtruth-trajectory",
        "candidateFrames": len(selected),
        "convertedFrames": converted,
        "selectedDepthTimestamps": selected_provenance,
        "pixelStride": pixel_stride,
        "depthScale": "uint16 / 5000 -> metres",
        "skipped": skipped,
    }


def canonicalize(mesh: Mesh, target_diagonal: float) -> dict:
    minimum = [min(vertex[axis] for vertex in mesh.vertices) for axis in range(3)]
    maximum = [max(vertex[axis] for vertex in mesh.vertices) for axis in range(3)]
    diagonal = math.sqrt(sum((maximum[axis] - minimum[axis]) ** 2 for axis in range(3)))
    if not math.isfinite(diagonal) or diagonal <= 1.0e-9:
        raise ValueError("native geometry has degenerate extent")
    center = [(minimum[axis] + maximum[axis]) * 0.5 for axis in range(3)]
    scale = target_diagonal / diagonal
    mesh.vertices = [
        (
            (vertex[0] - center[0]) * scale,
            (vertex[1] - center[1]) * scale,
            (vertex[2] - center[2]) * scale,
            vertex[3],
            vertex[4],
            vertex[5],
        )
        for vertex in mesh.vertices
    ]
    return {
        "scaleSource": "metric-source-canonicalized-for-broad-benchmark",
        "rawMetricBounds": {"minimum": minimum, "maximum": maximum},
        "rawMetricDiagonal": diagonal,
        "rawMetricCenter": center,
        "targetSceneDiagonalMetresByConvention": target_diagonal,
        "uniformScale": scale,
    }


def write_ply(path: Path, mesh: Mesh) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("ply\n")
        stream.write("format ascii 1.0\n")
        stream.write("comment MAVEB deterministic native-geometry broad-benchmark proxy\n")
        stream.write(f"element vertex {len(mesh.vertices)}\n")
        stream.write("property float x\nproperty float y\nproperty float z\n")
        stream.write("property float nx\nproperty float ny\nproperty float nz\n")
        stream.write("property uchar red\nproperty uchar green\nproperty uchar blue\n")
        stream.write(f"element face {len(mesh.faces)}\n")
        stream.write("property list uchar uint vertex_indices\n")
        stream.write("end_header\n")
        for x, y, z, red, green, blue in mesh.vertices:
            stream.write(f"{x:.9g} {y:.9g} {z:.9g} 0 0 1 {red} {green} {blue}\n")
        for a, b, c in mesh.faces:
            stream.write(f"3 {a} {b} {c}\n")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a canonical proxy from dataset-native geometry")
    parser.add_argument("--kind", choices=("3rscan", "arkitscenes", "bonn-rgbd"), required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-frames", type=int, default=40)
    parser.add_argument("--maximum-vertices", type=int, default=400000)
    parser.add_argument("--target-diagonal", type=float, default=2.0)
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fx", type=float, default=542.822841)
    parser.add_argument("--fy", type=float, default=542.576870)
    parser.add_argument("--cx", type=float, default=315.593520)
    parser.add_argument("--cy", type=float, default=237.756098)
    args = parser.parse_args(argv)

    if (
        args.max_frames < 2
        or args.maximum_vertices < 64
        or not math.isfinite(args.target_diagonal)
        or args.target_diagonal <= 0
        or args.width <= 0
        or args.height <= 0
        or min(args.fx, args.fy) <= 0
    ):
        parser.error("invalid native proxy configuration")

    source = args.source.resolve()
    output = args.output.resolve()
    try:
        if args.kind == "3rscan":
            mesh = obj_mesh(source)
            source_details = {
                "sourceRepresentation": "3rscan-provided-reference-mesh",
                "sourceGeometry": str(source),
                "sourceGeometrySha256": sha256(source),
            }
        elif args.kind == "arkitscenes":
            mesh, source_details = build_arkit(
                source, args.max_frames, args.maximum_vertices, args.ffmpeg
            )
        else:
            mesh, source_details = build_bonn(
                source,
                args.max_frames,
                args.maximum_vertices,
                args.ffmpeg,
                args.width,
                args.height,
                args.fx,
                args.fy,
                args.cx,
                args.cy,
            )
        scale = canonicalize(mesh, args.target_diagonal)
        write_ply(output, mesh)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"cbrc_native_proxy: {exc}", file=sys.stderr)
        return 2

    provenance = {
        "schemaVersion": 1,
        "artifact": "maveb-cbrc-native-geometry-proxy",
        "kind": args.kind,
        "source": str(source),
        "proxy": str(output),
        "proxySha256": sha256(output),
        "vertices": len(mesh.vertices),
        "faces": len(mesh.faces),
        "scale": scale,
        "sourceDetails": source_details,
        "scientificBoundary": (
            "Dataset-native geometry or registered depth+provided pose is used for world seeding. "
            "The source metric geometry is then uniformly canonicalized to the broad benchmark's "
            "2 m scene-diagonal convention; no RGB SfM or learned geometry reconstruction is used."
        ),
    }
    sidecar = Path(str(output) + ".source.json")
    sidecar.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(provenance, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
