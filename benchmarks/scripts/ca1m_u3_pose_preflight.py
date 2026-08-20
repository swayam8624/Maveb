#!/usr/bin/env python3
"""Validate CA-1M pose semantics before U3 geometry fusion.

The released CA-1M loader treats gt/RT as camera-to-world in the registered
laser-scanner coordinate frame. This preflight does not merely trust that
metadata: it cross-projects FARO depth between adjacent frames under both
possible rigid-pose interpretations and requires the released camera-to-world
interpretation to produce the better geometric consistency.

No ARKit confidence values, ARKit-vs-FARO residuals, or U3 reconstruction
outputs are used by this check.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import io
import json
import math
from pathlib import Path
import tarfile


REQUIRED_SUFFIXES = {
    "wide/depth",
    "wide/depth/k",
    "gt/depth",
    "gt/depth/k",
    "gt/rt",
}
MM_TO_M = 1000.0


@dataclass(frozen=True)
class FrameMembers:
    video_id: str
    timestamp: str
    members: dict[str, tarfile.TarInfo]


def member_identity(name: str) -> tuple[str, str, str] | None:
    clean = name.lstrip("./")
    if "/" not in clean:
        return None
    video_id, relative = clean.split("/", 1)
    if not video_id.isdigit() or "." not in relative:
        return None
    timestamp, suffix = relative.split(".", 1)
    if not timestamp.isdigit():
        return None
    suffix = suffix.lower()
    for extension in (".png", ".tiff", ".tif", ".json", ".txt"):
        if suffix.endswith(extension):
            suffix = suffix[: -len(extension)]
            break
    return video_id, timestamp, suffix


def discover_frames(archive: tarfile.TarFile, expected_video_id: str) -> list[FrameMembers]:
    grouped: dict[tuple[str, str], dict[str, tarfile.TarInfo]] = {}
    for member in archive.getmembers():
        if not member.isfile():
            continue
        identity = member_identity(member.name)
        if identity is None:
            continue
        video_id, timestamp, suffix = identity
        if video_id != expected_video_id or suffix not in REQUIRED_SUFFIXES:
            continue
        frame = grouped.setdefault((video_id, timestamp), {})
        if suffix in frame:
            raise ValueError(f"duplicate CA-1M member for {video_id}/{timestamp}: {suffix}")
        frame[suffix] = member
    frames = [
        FrameMembers(video_id, timestamp, members)
        for (video_id, timestamp), members in grouped.items()
        if REQUIRED_SUFFIXES.issubset(members)
    ]
    frames.sort(key=lambda frame: int(frame.timestamp))
    if len(frames) < 2:
        raise ValueError("archive contains fewer than two complete U3 frames")
    return frames


def read_member(archive: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    stream = archive.extractfile(member)
    if stream is None:
        raise ValueError(f"unable to read tar member: {member.name}")
    return stream.read()


def parse_matrix(data: bytes, size: int):
    import numpy as np

    payload = json.loads(data.decode("utf-8"))
    matrix = np.asarray(payload, dtype=np.float64).reshape(size, size)
    if not np.isfinite(matrix).all():
        raise ValueError(f"{size}x{size} matrix contains non-finite values")
    return matrix


def parse_intrinsics(data: bytes) -> tuple[float, float, float, float]:
    matrix = parse_matrix(data, 3)
    fx, fy, cx, cy = float(matrix[0, 0]), float(matrix[1, 1]), float(matrix[0, 2]), float(matrix[1, 2])
    if fx <= 0.0 or fy <= 0.0 or cx < 0.0 or cy < 0.0:
        raise ValueError("depth intrinsics are invalid")
    return fx, fy, cx, cy


def parse_pose(data: bytes):
    import numpy as np

    pose = parse_matrix(data, 4)
    if not np.allclose(pose[3], np.array([0.0, 0.0, 0.0, 1.0]), atol=1.0e-5):
        raise ValueError("gt/RT is not an affine rigid transform")
    rotation = pose[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=2.0e-3):
        raise ValueError("gt/RT rotation is not orthonormal")
    determinant = float(np.linalg.det(rotation))
    if abs(determinant - 1.0) > 2.0e-3:
        raise ValueError(f"gt/RT rotation determinant is {determinant}, expected +1")
    return pose


def decode_depth(data: bytes):
    import numpy as np
    from PIL import Image

    image = np.asarray(Image.open(io.BytesIO(data)))
    if image.ndim == 3 and image.shape[-1] == 1:
        image = image[..., 0]
    if image.ndim != 2:
        raise ValueError(f"expected single-channel depth image, got {image.shape}")
    return image.astype(np.float64) / MM_TO_M


def quantile_indices(count: int, view_count: int) -> list[int]:
    if view_count <= 0 or count < view_count:
        raise ValueError("view count exceeds available complete frames")
    if view_count == 1:
        return [0]
    result: list[int] = []
    for index in range(view_count):
        target = index * (count - 1) / (view_count - 1)
        lower = math.floor(target)
        upper = math.ceil(target)
        selected = lower if target - lower <= upper - target else upper
        result.append(selected)
    if len(set(result)) != view_count:
        raise ValueError("temporal quantile selection produced duplicate frame indices")
    return result


def pair_indices(count: int, pair_count: int) -> list[int]:
    available = count - 1
    return quantile_indices(available, min(pair_count, available))


def transform_points(points, pose, camera_to_world: bool):
    rotation = pose[:3, :3]
    translation = pose[:3, 3]
    if camera_to_world:
        return points @ rotation.T + translation
    return (points - translation) @ rotation


def world_to_camera(points, pose, camera_to_world: bool):
    rotation = pose[:3, :3]
    translation = pose[:3, 3]
    if camera_to_world:
        return (points - translation) @ rotation
    return points @ rotation.T + translation


def cross_project(
    source_depth,
    source_k: tuple[float, float, float, float],
    source_pose,
    target_depth,
    target_k: tuple[float, float, float, float],
    target_pose,
    *,
    camera_to_world: bool,
    pixel_stride: int,
) -> tuple[int, float | None, float | None]:
    import numpy as np

    source_height, source_width = source_depth.shape
    target_height, target_width = target_depth.shape
    sfx, sfy, scx, scy = source_k
    tfx, tfy, tcx, tcy = target_k

    ys = np.arange(pixel_stride // 2, source_height, pixel_stride, dtype=np.int64)
    xs = np.arange(pixel_stride // 2, source_width, pixel_stride, dtype=np.int64)
    grid_x, grid_y = np.meshgrid(xs, ys)
    z = source_depth[grid_y, grid_x]
    valid = np.isfinite(z) & (z > 0.0) & (z <= 20.0)
    if not np.any(valid):
        return 0, None, None

    x = (grid_x[valid].astype(np.float64) - scx) * z[valid] / sfx
    y = (grid_y[valid].astype(np.float64) - scy) * z[valid] / sfy
    camera_points = np.stack((x, y, z[valid]), axis=1)
    world_points = transform_points(camera_points, source_pose, camera_to_world)
    target_points = world_to_camera(world_points, target_pose, camera_to_world)

    positive = np.isfinite(target_points).all(axis=1) & (target_points[:, 2] > 0.05)
    target_points = target_points[positive]
    if target_points.size == 0:
        return 0, None, None

    projected_x = np.rint(tfx * target_points[:, 0] / target_points[:, 2] + tcx).astype(np.int64)
    projected_y = np.rint(tfy * target_points[:, 1] / target_points[:, 2] + tcy).astype(np.int64)
    inside = (
        (projected_x >= 0)
        & (projected_y >= 0)
        & (projected_x < target_width)
        & (projected_y < target_height)
    )
    target_points = target_points[inside]
    projected_x = projected_x[inside]
    projected_y = projected_y[inside]
    if target_points.size == 0:
        return 0, None, None

    observed = target_depth[projected_y, projected_x]
    valid_target = np.isfinite(observed) & (observed > 0.0) & (observed <= 20.0)
    predicted = target_points[valid_target, 2]
    observed = observed[valid_target]
    if predicted.size == 0:
        return 0, None, None

    errors = np.abs(predicted - observed)
    return int(errors.size), float(np.median(errors)), float(np.percentile(errors, 90.0))


def inspect_archive(path: Path, video_id: str, *, primary_views: int, validation_pairs: int, pixel_stride: int) -> dict:
    import numpy as np

    with tarfile.open(path, "r") as archive:
        frames = discover_frames(archive, video_id)
        selected_indices = quantile_indices(len(frames), primary_views)
        selected = [frames[index] for index in selected_indices]

        direct_medians: list[float] = []
        inverse_medians: list[float] = []
        pair_reports = []
        for source_index in pair_indices(len(frames), validation_pairs):
            source = frames[source_index]
            target = frames[source_index + 1]
            source_depth = decode_depth(read_member(archive, source.members["gt/depth"]))
            target_depth = decode_depth(read_member(archive, target.members["gt/depth"]))
            source_k = parse_intrinsics(read_member(archive, source.members["gt/depth/k"]))
            target_k = parse_intrinsics(read_member(archive, target.members["gt/depth/k"]))
            source_pose = parse_pose(read_member(archive, source.members["gt/rt"]))
            target_pose = parse_pose(read_member(archive, target.members["gt/rt"]))

            direct = cross_project(
                source_depth,
                source_k,
                source_pose,
                target_depth,
                target_k,
                target_pose,
                camera_to_world=True,
                pixel_stride=pixel_stride,
            )
            inverse = cross_project(
                source_depth,
                source_k,
                source_pose,
                target_depth,
                target_k,
                target_pose,
                camera_to_world=False,
                pixel_stride=pixel_stride,
            )
            if direct[1] is not None:
                direct_medians.append(direct[1])
            if inverse[1] is not None:
                inverse_medians.append(inverse[1])
            pair_reports.append(
                {
                    "sourceTimestampNanoseconds": int(source.timestamp),
                    "targetTimestampNanoseconds": int(target.timestamp),
                    "cameraToWorld": {
                        "validCorrespondences": direct[0],
                        "medianAbsDepthErrorMetres": direct[1],
                        "p90AbsDepthErrorMetres": direct[2],
                    },
                    "inverseInterpretation": {
                        "validCorrespondences": inverse[0],
                        "medianAbsDepthErrorMetres": inverse[1],
                        "p90AbsDepthErrorMetres": inverse[2],
                    },
                }
            )

        if not direct_medians or not inverse_medians:
            raise ValueError("pose preflight produced no comparable adjacent-frame depth pairs")
        direct_scene_median = float(np.median(np.asarray(direct_medians)))
        inverse_scene_median = float(np.median(np.asarray(inverse_medians)))
        comparable = [
            pair
            for pair in pair_reports
            if pair["cameraToWorld"]["medianAbsDepthErrorMetres"] is not None
            and pair["inverseInterpretation"]["medianAbsDepthErrorMetres"] is not None
        ]
        direct_wins = sum(
            pair["cameraToWorld"]["medianAbsDepthErrorMetres"]
            < pair["inverseInterpretation"]["medianAbsDepthErrorMetres"]
            for pair in comparable
        )
        pass_pose = (
            len(comparable) >= max(3, min(8, validation_pairs // 2))
            and direct_wins > len(comparable) / 2
            and direct_scene_median < inverse_scene_median
        )

        selected_records = []
        for original_index, frame in zip(selected_indices, selected):
            pose = parse_pose(read_member(archive, frame.members["gt/rt"]))
            arkit_depth = decode_depth(read_member(archive, frame.members["wide/depth"]))
            faro_depth = decode_depth(read_member(archive, frame.members["gt/depth"]))
            arkit_k = parse_intrinsics(read_member(archive, frame.members["wide/depth/k"]))
            faro_k = parse_intrinsics(read_member(archive, frame.members["gt/depth/k"]))
            selected_records.append(
                {
                    "originalCompleteFrameIndex": original_index,
                    "timestampNanoseconds": int(frame.timestamp),
                    "arkitDepthShape": list(arkit_depth.shape),
                    "faroDepthShape": list(faro_depth.shape),
                    "arkitDepthIntrinsics": list(arkit_k),
                    "faroDepthIntrinsics": list(faro_k),
                    "cameraToWorldTranslationMetres": [float(value) for value in pose[:3, 3]],
                }
            )

        return {
            "videoId": video_id,
            "archive": str(path),
            "completeFrames": len(frames),
            "primaryEightViewSelection": selected_records,
            "poseConventionValidation": {
                "comparison": "released camera-to-world interpretation versus inverse interpretation",
                "pairCount": len(comparable),
                "cameraToWorldBetterPairCount": direct_wins,
                "cameraToWorldMedianOfPairMedianErrorsMetres": direct_scene_median,
                "inverseMedianOfPairMedianErrorsMetres": inverse_scene_median,
                "passed": pass_pose,
                "pairs": pair_reports,
            },
        }


def video_id_from_path(path: Path) -> str:
    stem = path.stem
    video_id = stem.rsplit("-", 1)[-1]
    if not video_id.isdigit():
        raise ValueError(f"unable to infer video id from archive name: {path.name}")
    return video_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--primary-views", type=int, default=8)
    parser.add_argument("--validation-pairs", type=int, default=16)
    parser.add_argument("--pixel-stride", type=int, default=16)
    args = parser.parse_args()

    if args.primary_views <= 1 or args.validation_pairs <= 0 or args.pixel_stride <= 0:
        raise ValueError("preflight view/pair/stride arguments are invalid")

    scenes = []
    for archive in args.archives:
        if not archive.is_file():
            raise FileNotFoundError(archive)
        scenes.append(
            inspect_archive(
                archive,
                video_id_from_path(archive),
                primary_views=args.primary_views,
                validation_pairs=args.validation_pairs,
                pixel_stride=args.pixel_stride,
            )
        )

    passed = all(scene["poseConventionValidation"]["passed"] for scene in scenes)
    payload = {
        "schemaVersion": 1,
        "study": "metric-uncertainty-v1",
        "stage": "U3-ca1m-pose-preflight",
        "status": "passed" if passed else "failed",
        "poseInterpretation": "gt/RT is camera-to-world in FARO laser-scanner coordinates",
        "cameraConvention": "+X right, +Y down, +Z forward",
        "frameSelectionFormula": "nearest index to i*(N-1)/(K-1), ties to lower index",
        "primaryViewCount": args.primary_views,
        "validationPairCountRequested": args.validation_pairs,
        "pixelStride": args.pixel_stride,
        "scenes": scenes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
