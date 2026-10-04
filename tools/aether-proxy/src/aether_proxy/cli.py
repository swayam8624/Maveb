from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
import sys
from typing import NoReturn

from . import __version__


MAX_LINE_BYTES = 16 * 1024 * 1024
MAX_POINTS = 100_000_000
CONFIG_FIELDS = {
    "minimumPoints": "minimum_points",
    "minimumTrackLength": "minimum_track_length",
    "maximumReprojectionError": "maximum_reprojection_error",
    "voxelSize": "voxel_size",
    "normalRadiusMultiplier": "normal_radius_multiplier",
    "normalMaxNeighbors": "normal_max_neighbors",
    "poissonDepth": "poisson_depth",
    "densityQuantile": "density_quantile",
    "targetTriangles": "target_triangles",
    "threads": "threads",
    "seed": "seed",
}


class ProxyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProxyConfig:
    minimum_points: int = 100
    minimum_track_length: int = 2
    maximum_reprojection_error: float = 4.0
    voxel_size: float = 0.0
    normal_radius_multiplier: float = 4.0
    normal_max_neighbors: int = 64
    poisson_depth: int = 9
    density_quantile: float = 0.02
    target_triangles: int = 250_000
    threads: int = 1
    seed: int = 42

    @classmethod
    def load(cls, path: Path | None) -> "ProxyConfig":
        if path is None:
            config = cls()
        else:
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise ProxyError(f"Unable to read proxy configuration: {error}") from error
            if document.get("schemaVersion") != 1:
                raise ProxyError("Proxy configuration schemaVersion must be 1")
            unknown = set(document) - set(CONFIG_FIELDS) - {"schemaVersion"}
            if unknown:
                raise ProxyError(f"Unknown proxy configuration fields: {', '.join(sorted(unknown))}")
            config = cls(**{internal: document[external]
                           for external, internal in CONFIG_FIELDS.items() if external in document})
        config.validate()
        return config

    def validate(self) -> None:
        numeric = asdict(self)
        if any(isinstance(value, float) and not math.isfinite(value) for value in numeric.values()):
            raise ProxyError("Proxy configuration contains a non-finite number")
        if not 3 <= self.minimum_points <= MAX_POINTS:
            raise ProxyError("minimum_points is outside the supported range")
        if not 2 <= self.minimum_track_length <= 1_000_000:
            raise ProxyError("minimum_track_length is outside the supported range")
        if self.maximum_reprojection_error <= 0 or self.voxel_size < 0:
            raise ProxyError("Reprojection error and voxel size must be positive")
        if self.normal_radius_multiplier <= 0 or not 3 <= self.normal_max_neighbors <= 10_000:
            raise ProxyError("Normal estimation settings are invalid")
        if not 5 <= self.poisson_depth <= 13 or not 0 <= self.density_quantile < 0.5:
            raise ProxyError("Poisson reconstruction settings are invalid")
        if not 4 <= self.target_triangles <= 100_000_000 or not 1 <= self.threads <= 64:
            raise ProxyError("Proxy output budget or thread count is invalid")
        if not 0 <= self.seed <= 0xFFFFFFFF:
            raise ProxyError("Proxy seed is outside the uint32 range")

    def json_document(self) -> dict[str, object]:
        values = asdict(self)
        return {external: values[internal] for external, internal in CONFIG_FIELDS.items()}


def parse_colmap_points(path: Path, config: ProxyConfig) -> tuple[list[list[float]], list[list[float]]]:
    points: list[list[float]] = []
    colors: list[list[float]] = []
    seen: set[int] = set()
    try:
        stream = path.open("r", encoding="utf-8")
    except OSError as error:
        raise ProxyError(f"Unable to open COLMAP points3D.txt: {error}") from error
    with stream:
        for line_number, line in enumerate(stream, 1):
            if len(line.encode("utf-8")) > MAX_LINE_BYTES:
                raise ProxyError(f"points3D.txt line {line_number} exceeds the safety limit")
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            fields = stripped.split()
            if len(fields) < 12 or (len(fields) - 8) % 2 != 0:
                raise ProxyError(f"Malformed COLMAP point at line {line_number}")
            try:
                point_id = int(fields[0])
                xyz = [float(value) for value in fields[1:4]]
                rgb = [int(value) for value in fields[4:7]]
                error = float(fields[7])
                track = [(int(fields[index]), int(fields[index + 1]))
                         for index in range(8, len(fields), 2)]
            except ValueError as parse_error:
                raise ProxyError(f"Invalid COLMAP scalar at line {line_number}") from parse_error
            if point_id <= 0 or point_id in seen or not all(math.isfinite(value) for value in xyz):
                raise ProxyError(f"Invalid or duplicate COLMAP point at line {line_number}")
            if not math.isfinite(error) or error < 0 or any(value < 0 or value > 255 for value in rgb):
                raise ProxyError(f"Invalid COLMAP point attributes at line {line_number}")
            if any(image_id <= 0 or observation < 0 for image_id, observation in track):
                raise ProxyError(f"Invalid COLMAP track at line {line_number}")
            seen.add(point_id)
            unique_images = {image_id for image_id, _ in track}
            if len(unique_images) >= config.minimum_track_length and error <= config.maximum_reprojection_error:
                points.append(xyz)
                colors.append([value / 255.0 for value in rgb])
                if len(points) > MAX_POINTS:
                    raise ProxyError("Accepted COLMAP point count exceeds the safety limit")
    if len(points) < config.minimum_points:
        raise ProxyError(
            f"Only {len(points)} reliable sparse points remain; {config.minimum_points} are required"
        )
    return points, colors


def atomic_json(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
                             encoding="utf-8")
        os.replace(temporary, path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise ProxyError(f"Unable to write proxy report: {error}") from error


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
    except OSError as error:
        raise ProxyError(f"Unable to hash {path}: {error}") from error
    return digest.hexdigest()


def reconstruct(points_path: Path, output_path: Path, report_path: Path,
                config: ProxyConfig) -> dict[str, object]:
    try:
        import numpy as np
        import open3d as o3d
    except ImportError as error:
        raise ProxyError("Pinned Open3D environment is unavailable; run bootstrap-reconstruction.zsh") from error

    if output_path.suffix.lower() != ".ply":
        raise ProxyError("Proxy output must use the .ply extension")
    if points_path.resolve() in {output_path.resolve(), report_path.resolve()} or \
            output_path.resolve() == report_path.resolve():
        raise ProxyError("Proxy input, mesh output, and report paths must be distinct")
    input_hash = sha256_file(points_path)
    points, colors = parse_colmap_points(points_path, config)
    if sha256_file(points_path) != input_hash:
        raise ProxyError("COLMAP points changed while the proxy job was reading them")
    xyz = np.asarray(points, dtype=np.float64)
    diagonal = float(np.linalg.norm(np.max(xyz, axis=0) - np.min(xyz, axis=0)))
    if not math.isfinite(diagonal) or diagonal <= 1.0e-9:
        raise ProxyError("Reliable COLMAP points have a degenerate spatial extent")
    voxel_size = config.voxel_size if config.voxel_size > 0 else diagonal / 256.0
    o3d.utility.random.seed(config.seed)
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(xyz)
    cloud.colors = o3d.utility.Vector3dVector(np.asarray(colors, dtype=np.float64))
    cloud = cloud.voxel_down_sample(voxel_size)
    if len(cloud.points) < config.minimum_points:
        raise ProxyError("Voxel filtering left too few points for proxy reconstruction")
    cloud.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(
        radius=voxel_size * config.normal_radius_multiplier,
        max_nn=config.normal_max_neighbors))
    cloud.orient_normals_consistent_tangent_plane(min(30, len(cloud.points) - 1))
    mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
        cloud, depth=config.poisson_depth, scale=1.1, linear_fit=False, n_threads=config.threads)
    densities_array = np.asarray(densities)
    if densities_array.size == 0 or len(mesh.triangles) == 0:
        raise ProxyError("Poisson reconstruction produced an empty mesh")
    threshold = float(np.quantile(densities_array, config.density_quantile))
    mesh.remove_vertices_by_mask(densities_array < threshold)
    bounds = cloud.get_axis_aligned_bounding_box()
    bounds = bounds.scale(1.05, bounds.get_center())
    mesh = mesh.crop(bounds)
    mesh.remove_duplicated_vertices()
    mesh.remove_duplicated_triangles()
    mesh.remove_degenerate_triangles()
    mesh.remove_non_manifold_edges()
    mesh.remove_unreferenced_vertices()
    if len(mesh.triangles) > config.target_triangles:
        mesh = mesh.simplify_quadric_decimation(config.target_triangles)
    mesh.compute_vertex_normals(normalized=True)
    if len(mesh.vertices) < 3 or len(mesh.triangles) < 1:
        raise ProxyError("Proxy cleanup produced an empty mesh")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output_path.with_name(output_path.stem + ".tmp" + output_path.suffix)
    try:
        if not o3d.io.write_triangle_mesh(str(temporary_output), mesh, write_ascii=False,
                                          compressed=True, write_vertex_normals=True,
                                          write_vertex_colors=True):
            raise ProxyError("Open3D failed to write the proxy mesh")
        os.replace(temporary_output, output_path)
    except OSError as error:
        temporary_output.unlink(missing_ok=True)
        raise ProxyError(f"Unable to finalize proxy mesh: {error}") from error
    document: dict[str, object] = {
        "schemaVersion": 1,
        "tool": {"name": "aether-proxy", "version": __version__, "open3d": o3d.__version__},
        "input": {"path": str(points_path), "sha256": input_hash,
                  "acceptedPoints": len(points)},
        "output": {"path": str(output_path), "vertices": len(mesh.vertices),
                   "triangles": len(mesh.triangles), "sha256": sha256_file(output_path)},
        "spatialDiagonal": diagonal,
        "effectiveVoxelSize": voxel_size,
        "densityThreshold": threshold,
        "config": config.json_document(),
    }
    atomic_json(report_path, document)
    return document


def fail(message: str, json_output: bool, code: int = 2) -> NoReturn:
    if json_output:
        print(json.dumps({"ok": False, "error": {"code": "proxy-error", "message": message}},
                         separators=(",", ":")), file=sys.stderr)
    else:
        print(message, file=sys.stderr)
    raise SystemExit(code)


def main() -> None:
    parser = argparse.ArgumentParser(prog="aether-proxy")
    parser.add_argument("points", nargs="?", type=Path, help="COLMAP points3D.txt")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--version", action="store_true")
    arguments = parser.parse_args()
    if arguments.version:
        try:
            import open3d as o3d
            print(f"aether-proxy {__version__} (Open3D {o3d.__version__})")
        except ImportError as error:
            fail(str(error), arguments.json)
        return
    if arguments.points is None or arguments.output is None:
        fail("points3D.txt and --output are required", arguments.json)
    report = arguments.report or arguments.output.with_suffix(".json")
    try:
        document = reconstruct(arguments.points, arguments.output, report,
                               ProxyConfig.load(arguments.config))
    except ProxyError as error:
        fail(str(error), arguments.json)
    except (OSError, RuntimeError, ValueError) as error:
        fail(f"Proxy reconstruction failed: {error}", arguments.json)
    if arguments.json:
        print(json.dumps({"ok": True, "output": document["output"], "report": str(report)},
                         separators=(",", ":")))
    else:
        print(f"Proxy mesh written to {arguments.output}")


if __name__ == "__main__":
    main()
