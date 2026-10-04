#!/usr/bin/env python3
"""Seed a MAVEB persistent Gaussian world from a real COLMAP sparse reconstruction.

The source is ordinary-camera SfM. Raw COLMAP global scale is arbitrary, so this
tool applies an explicit canonical scene-diagonal normalization and records that
fact in provenance rather than pretending the source is metrically calibrated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SH_C0 = 0.28209479177387814
GAUSSIAN_HEADER_BYTES = 32
GAUSSIAN_RECORD_BYTES = 256
OWNERSHIP_HEADER_BYTES = 32


@dataclass(frozen=True)
class Point:
    point_id: int
    xyz: tuple[float, float, float]
    rgb: tuple[int, int, int]
    error: float
    track_length: int


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_exact(stream, size: int) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise ValueError("COLMAP binary model is truncated")
    return data


def read_points_binary(path: Path) -> Iterable[Point]:
    with path.open("rb") as stream:
        count = struct.unpack("<Q", read_exact(stream, 8))[0]
        if count <= 0 or count > 100_000_000:
            raise ValueError(f"invalid COLMAP point count: {count}")
        for _ in range(count):
            record = struct.unpack("<QdddBBBd", read_exact(stream, 43))
            point_id = int(record[0])
            xyz = tuple(float(v) for v in record[1:4])
            rgb = tuple(int(v) for v in record[4:7])
            error = float(record[7])
            track_length = struct.unpack("<Q", read_exact(stream, 8))[0]
            if track_length > 100_000_000:
                raise ValueError("COLMAP point track is implausibly large")
            skip = int(track_length) * 8
            if skip:
                read_exact(stream, skip)
            yield Point(point_id, xyz, rgb, error, int(track_length))
        if stream.read(1):
            raise ValueError("COLMAP points3D.bin has trailing bytes")


def read_points_text(path: Path) -> Iterable[Point]:
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.split()
            if len(fields) < 8 or (len(fields) - 8) % 2:
                raise ValueError(f"invalid COLMAP points3D.txt row {line_number}")
            point_id = int(fields[0])
            xyz = tuple(float(v) for v in fields[1:4])
            rgb = tuple(int(v) for v in fields[4:7])
            error = float(fields[7])
            track_length = (len(fields) - 8) // 2
            yield Point(point_id, xyz, rgb, error, track_length)


def load_points(model_dir: Path) -> tuple[list[Point], Path]:
    binary = model_dir / "points3D.bin"
    text = model_dir / "points3D.txt"
    if binary.is_file():
        points = list(read_points_binary(binary))
        source = binary
    elif text.is_file():
        points = list(read_points_text(text))
        source = text
    else:
        raise FileNotFoundError(
            f"{model_dir} contains neither points3D.bin nor points3D.txt"
        )
    return points, source


def finite_point(point: Point) -> bool:
    return (
        all(math.isfinite(v) and abs(v) <= 1.0e12 for v in point.xyz)
        and math.isfinite(point.error)
        and point.error >= 0.0
        and all(0 <= c <= 255 for c in point.rgb)
        and point.point_id > 0
    )


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("percentile requires values")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def bounds(points: list[Point]) -> tuple[list[float], list[float]]:
    minimum = [min(point.xyz[axis] for point in points) for axis in range(3)]
    maximum = [max(point.xyz[axis] for point in points) for axis in range(3)]
    return minimum, maximum


def diagonal(minimum: list[float], maximum: list[float]) -> float:
    return math.sqrt(sum((maximum[i] - minimum[i]) ** 2 for i in range(3)))


def canonicalize(
    points: list[Point],
    target_diagonal: float,
) -> tuple[list[Point], dict]:
    raw_min, raw_max = bounds(points)
    raw_diagonal = diagonal(raw_min, raw_max)
    if not math.isfinite(raw_diagonal) or raw_diagonal <= 1.0e-12:
        raise ValueError("COLMAP point cloud has degenerate extent")

    center = [(raw_min[i] + raw_max[i]) * 0.5 for i in range(3)]
    scale = target_diagonal / raw_diagonal
    canonical = []
    for point in points:
        xyz = tuple((point.xyz[i] - center[i]) * scale for i in range(3))
        canonical.append(
            Point(point.point_id, xyz, point.rgb, point.error, point.track_length)
        )
    return canonical, {
        "scaleSource": "canonical-normalization-not-measured",
        "targetSceneDiagonalMetres": target_diagonal,
        "rawSceneDiagonal": raw_diagonal,
        "rawCenter": center,
        "uniformScale": scale,
    }


def select_points(
    points: list[Point],
    minimum_track: int,
    maximum_error: float | None,
    maximum_points: int,
) -> tuple[list[Point], dict]:
    valid = [point for point in points if finite_point(point)]
    if not valid:
        raise ValueError("COLMAP reconstruction has no finite points")

    auto_error = percentile([p.error for p in valid], 0.95)
    threshold = auto_error if maximum_error is None else maximum_error
    filtered = [
        point
        for point in valid
        if point.track_length >= minimum_track and point.error <= threshold
    ]
    if len(filtered) < 64:
        raise ValueError(
            f"only {len(filtered)} COLMAP points survive quality filters; need at least 64"
        )

    filtered.sort(key=lambda point: point.point_id)
    stride = max(1, math.ceil(len(filtered) / maximum_points))
    selected = filtered[::stride]
    if len(selected) > maximum_points:
        selected = selected[:maximum_points]

    return selected, {
        "inputPoints": len(points),
        "finitePoints": len(valid),
        "minimumTrackLength": minimum_track,
        "maximumReprojectionError": threshold,
        "autoError95thPercentile": auto_error,
        "qualityFilteredPoints": len(filtered),
        "deterministicStride": stride,
        "selectedPoints": len(selected),
    }


def fnv_signature(values: tuple[int, int, int], count: int, salt: int) -> int:
    value = 1469598103934665603 ^ salt
    for raw in (*values, count):
        unsigned = raw & ((1 << 64) - 1)
        for shift in range(0, 64, 8):
            value ^= (unsigned >> shift) & 0xFF
            value = (value * 1099511628211) & ((1 << 64) - 1)
    return value


def confidence(point: Point, error_threshold: float) -> float:
    track = min(1.0, math.log1p(point.track_length) / math.log(21.0))
    if error_threshold <= 0:
        reprojection = 1.0
    else:
        reprojection = math.exp(-point.error / max(error_threshold, 1.0e-9))
    return min(1.0, max(0.0, 0.35 + 0.65 * track * reprojection))


def spatial_partition(
    points: list[Point],
    cell_size: float,
    gaussian_scale: float,
    error_threshold: float,
) -> tuple[list[int], list[dict]]:
    cells: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for index, point in enumerate(points):
        key = tuple(math.floor(value / cell_size) for value in point.xyz)
        cells[key].append(index)

    if len(cells) < 2:
        raise ValueError(
            "COLMAP seeding produced fewer than two spatial owners; reduce --cell-size"
        )

    owners = [0] * len(points)
    entities = []
    support = 3.0 * gaussian_scale
    for entity_id, key in enumerate(sorted(cells), 1):
        indices = cells[key]
        centroid = [
            sum(points[index].xyz[axis] for index in indices) / len(indices)
            for axis in range(3)
        ]
        minimum = [
            min(points[index].xyz[axis] for index in indices) - support
            for axis in range(3)
        ]
        maximum = [
            max(points[index].xyz[axis] for index in indices) + support
            for axis in range(3)
        ]
        mean_confidence = sum(
            confidence(points[index], error_threshold) for index in indices
        ) / len(indices)
        geometry_signature = fnv_signature(key, len(indices), 0x434F4C4D41504745)
        appearance_signature = fnv_signature(key, len(indices), 0x524742434F4C4F52)
        entities.append(
            {
                "id": entity_id,
                "name": f"sfm-cell-{entity_id}",
                "semanticLabel": "spatial-sfm-cell",
                "translation": centroid,
                "rotation": [0.0, 0.0, 0.0, 1.0],
                "scale": [1.0, 1.0, 1.0],
                "boundsMinimum": minimum,
                "boundsMaximum": maximum,
                "representation": 2,
                "geometrySignature": geometry_signature,
                "appearanceSignature": appearance_signature,
                "confidence": mean_confidence,
                "lastObserved": 1_000_000_000,
            }
        )
        for index in indices:
            owners[index] = entity_id

    return owners, entities


def gaussian_record(
    point: Point,
    log_scale: float,
    opacity_logit: float,
) -> bytes:
    dc = tuple((channel / 255.0 - 0.5) / SH_C0 for channel in point.rgb)
    values = [
        *point.xyz,
        log_scale,
        log_scale,
        log_scale,
        1.0,
        0.0,
        0.0,
        0.0,
        opacity_logit,
        *dc,
        *([0.0] * 45),
    ]
    payload = struct.pack("<" + "f" * len(values), *values)
    payload += struct.pack("<I", 0)
    if len(payload) > GAUSSIAN_RECORD_BYTES:
        raise AssertionError("Gaussian record overflow")
    return payload + bytes(GAUSSIAN_RECORD_BYTES - len(payload))


def encode_gaussians(
    points: list[Point],
    gaussian_scale: float,
    opacity: float,
) -> bytes:
    header = (
        b"AETHGS\x00\x00"
        + struct.pack("<HHI", 1, 0, GAUSSIAN_RECORD_BYTES)
        + struct.pack("<QII", len(points), 0, 0)
    )
    log_scale = math.log(gaussian_scale)
    opacity_logit = math.log(opacity / (1.0 - opacity))
    return header + b"".join(
        gaussian_record(point, log_scale, opacity_logit) for point in points
    )


def encode_ownership(owners: list[int]) -> bytes:
    header = (
        b"MVGOWNR\x00"
        + struct.pack("<II", 1, OWNERSHIP_HEADER_BYTES)
        + struct.pack("<QQ", len(owners), 0)
    )
    return header + b"".join(struct.pack("<Q", owner) for owner in owners)


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(data)
        temp_path = Path(temporary.name)
    os.replace(temp_path, path)


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, mode="w", encoding="utf-8", delete=False
    ) as temporary:
        temporary.write(text)
        temp_path = Path(temporary.name)
    os.replace(temp_path, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scene-id", required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--archive-sha256")
    parser.add_argument("--scene-diagonal-metres", type=float, default=2.0)
    parser.add_argument("--cell-size", type=float, default=0.0)
    parser.add_argument("--gaussian-scale", type=float, default=0.0)
    parser.add_argument("--opacity", type=float, default=0.85)
    parser.add_argument("--minimum-track-length", type=int, default=3)
    parser.add_argument("--maximum-reprojection-error", type=float)
    parser.add_argument("--maximum-points", type=int, default=750_000)
    args = parser.parse_args()

    if (
        not math.isfinite(args.scene_diagonal_metres)
        or args.scene_diagonal_metres <= 0
        or not math.isfinite(args.cell_size)
        or args.cell_size < 0
        or not math.isfinite(args.gaussian_scale)
        or args.gaussian_scale < 0
        or not math.isfinite(args.opacity)
        or not 0 < args.opacity < 1
        or args.minimum_track_length < 1
        or args.maximum_points < 64
    ):
        parser.error("invalid numeric seeding configuration")
    if args.maximum_reprojection_error is not None and (
        not math.isfinite(args.maximum_reprojection_error)
        or args.maximum_reprojection_error < 0
    ):
        parser.error("maximum reprojection error must be finite/non-negative")

    model_dir = args.model_dir.resolve()
    raw, points_path = load_points(model_dir)
    selected, filtering = select_points(
        raw,
        args.minimum_track_length,
        args.maximum_reprojection_error,
        args.maximum_points,
    )
    points, scale_provenance = canonicalize(
        selected,
        args.scene_diagonal_metres,
    )

    canonical_min, canonical_max = bounds(points)
    canonical_diagonal = diagonal(canonical_min, canonical_max)
    cell_size = (
        args.cell_size
        if args.cell_size > 0
        else max(0.03, canonical_diagonal / 7.0)
    )
    density_scale = (
        0.65 * canonical_diagonal / max(len(points), 1) ** (1.0 / 3.0)
    )
    gaussian_scale = (
        args.gaussian_scale
        if args.gaussian_scale > 0
        else min(max(density_scale, 0.002), max(0.002, cell_size / 5.0))
    )

    owners, entities = spatial_partition(
        points,
        cell_size,
        gaussian_scale,
        float(filtering["maximumReprojectionError"]),
    )

    world = {
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

    output = args.output.resolve()
    gaussian_path = Path(str(output) + ".gaussians.r1.bin")
    ownership_path = Path(str(output) + ".ownership.r1.bin")
    provenance_path = Path(str(output) + ".source.json")

    atomic_text(output, json.dumps(world, indent=2, sort_keys=True) + "\n")
    atomic_bytes(
        gaussian_path,
        encode_gaussians(points, gaussian_scale, args.opacity),
    )
    atomic_bytes(ownership_path, encode_ownership(owners))

    provenance = {
        "schemaVersion": 1,
        "artifact": "maveb-public-colmap-world-seed",
        "sceneId": args.scene_id,
        "sourceId": args.source_id,
        "sourceUrl": args.source_url,
        "archiveSha256": args.archive_sha256,
        "colmapModelDir": str(model_dir),
        "pointsPath": str(points_path),
        "pointsSha256": sha256(points_path),
        "sourceRepresentation": "ordinary-RGB-derived-COLMAP-sparse-SfM",
        "ownershipMode": "deterministic-spatial-grid-not-semantic",
        "gaussianInitialization": "isotropic-sparse-SfM-seed-not-trained-3DGS",
        "filtering": filtering,
        "scale": scale_provenance,
        "canonicalBounds": {
            "minimum": canonical_min,
            "maximum": canonical_max,
            "diagonalMetresByConvention": canonical_diagonal,
        },
        "cellSizeMetresByConvention": cell_size,
        "gaussianScaleMetresByConvention": gaussian_scale,
        "opacity": args.opacity,
        "entities": len(entities),
        "gaussians": len(points),
        "worldSha256": sha256(output),
        "gaussianSha256": sha256(gaussian_path),
        "ownershipSha256": sha256(ownership_path),
        "scientificBoundary": (
            "Real RGB-derived geometry and color; global metric scale is canonicalized, "
            "not sensor-measured. Do not claim metric reconstruction accuracy or trained "
            "photorealistic 3DGS from this seeded representation."
        ),
    }
    atomic_text(
        provenance_path,
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
    )
    print(json.dumps(provenance, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
