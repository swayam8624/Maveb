#!/usr/bin/env python3
"""Generate metric uncertainty observations from CA-1M ARKit depth vs FARO GT depth.

CA-1M packages onboard ARKit LiDAR depth and independently rendered FARO laser-scanner depth for the
same oriented camera frame. The two depth maps have separate calibrated intrinsics, so samples are
matched by camera ray rather than by assuming a fixed 2x pixel resize. Confidence is consumed exactly
as CA-1M releases it: a [0, 1] per-depth value. Ground-truth zeros are treated as unregistered and are
never converted into error samples.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import io
import json
import math
from pathlib import Path
import tarfile
from typing import Iterator


REQUIRED_SUFFIXES = {
    "wide/depth",
    "wide/depth/k",
    "wide/depth/confidence",
    "gt/depth",
    "gt/depth/k",
}
MM_TO_M = 1000.0


@dataclass(frozen=True)
class FrameMembers:
    video_id: str
    timestamp: str
    members: dict[str, tarfile.TarInfo]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def member_identity(name: str) -> tuple[str, str, str] | None:
    """Map a CA-1M tar member to (video_id, integer_timestamp, normalized suffix)."""

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
    if not frames:
        raise ValueError(
            "archive contains no complete CA-1M frames with ARKit depth/confidence and FARO GT depth"
        )
    return frames


def read_member(archive: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    stream = archive.extractfile(member)
    if stream is None:
        raise ValueError(f"unable to read tar member: {member.name}")
    return stream.read()


def parse_intrinsics(data: bytes) -> tuple[float, float, float, float]:
    matrix = json.loads(data.decode("utf-8"))
    flat = []
    if isinstance(matrix, list):
        for value in matrix:
            if isinstance(value, list):
                flat.extend(value)
            else:
                flat.append(value)
    if len(flat) != 9:
        raise ValueError("CA-1M depth intrinsics must contain 9 values")
    values = [float(value) for value in flat]
    if any(not math.isfinite(value) for value in values):
        raise ValueError("CA-1M depth intrinsics contain non-finite values")
    fx, fy, cx, cy = values[0], values[4], values[2], values[5]
    if fx <= 0.0 or fy <= 0.0:
        raise ValueError("CA-1M depth focal lengths must be positive")
    return fx, fy, cx, cy


def decode_image(data: bytes):
    try:
        import numpy as np
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("CA-1M sampling requires NumPy and Pillow") from exc
    image = np.asarray(Image.open(io.BytesIO(data)))
    if image.ndim == 3 and image.shape[-1] == 1:
        image = image[..., 0]
    if image.ndim != 2:
        raise ValueError(f"expected a single-channel CA-1M depth/confidence image, got {image.shape}")
    return image


def project_pixel_between_intrinsics(
    x: int,
    y: int,
    source_k: tuple[float, float, float, float],
    target_k: tuple[float, float, float, float],
) -> tuple[float, float]:
    source_fx, source_fy, source_cx, source_cy = source_k
    target_fx, target_fy, target_cx, target_cy = target_k
    nx = (float(x) - source_cx) / source_fx
    ny = (float(y) - source_cy) / source_fy
    return target_fx * nx + target_cx, target_fy * ny + target_cy


def confidence_value(raw) -> float:
    value = float(raw)
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        raise ValueError(
            f"CA-1M confidence must use the documented [0, 1] representation, got {value}"
        )
    return value


def sample_frame(
    *,
    scene: str,
    frame: FrameMembers,
    arkit_depth,
    confidence,
    gt_depth,
    arkit_k: tuple[float, float, float, float],
    gt_k: tuple[float, float, float, float],
    pixel_stride: int,
    maximum_depth_metres: float,
) -> Iterator[dict]:
    if arkit_depth.shape != confidence.shape:
        raise ValueError("CA-1M ARKit depth and confidence dimensions differ")
    height, width = arkit_depth.shape
    gt_height, gt_width = gt_depth.shape
    focal = math.sqrt(arkit_k[0] * arkit_k[1])
    start = pixel_stride // 2
    for y in range(start, height, pixel_stride):
        for x in range(start, width, pixel_stride):
            observed = float(arkit_depth[y, x]) / MM_TO_M
            if not math.isfinite(observed) or observed <= 0.0 or observed > maximum_depth_metres:
                continue
            gx, gy = project_pixel_between_intrinsics(x, y, arkit_k, gt_k)
            gxi, gyi = int(round(gx)), int(round(gy))
            if gxi < 0 or gyi < 0 or gxi >= gt_width or gyi >= gt_height:
                continue
            reference = float(gt_depth[gyi, gxi]) / MM_TO_M
            if not math.isfinite(reference) or reference <= 0.0 or reference > maximum_depth_metres:
                continue
            sensor_confidence = confidence_value(confidence[y, x])
            yield {
                "scene": scene,
                "sampleId": f"{frame.video_id}-{frame.timestamp}-x{x}-y{y}",
                "videoId": frame.video_id,
                "timestampNanoseconds": int(frame.timestamp),
                "pixelX": x,
                "pixelY": y,
                "gtPixelX": gxi,
                "gtPixelY": gyi,
                "depthMetres": observed,
                "referenceDepthMetres": reference,
                "signedErrorMetres": observed - reference,
                "sensorConfidence": sensor_confidence,
                "confidenceSource": "CA-1M released ARKit depth confidence [0,1]",
                "poseConfidence": 1.0,
                "reprojectionErrorPixels": 0.0,
                "focalLengthPixels": focal,
                "alignmentPositionRmseMetres": 0.0,
                "alignmentOrientationErrorDegrees": 0.0,
                "groundTruthSource": "CA-1M FARO laser-scanner rendered depth",
            }


def generate_samples(
    archive_path: Path,
    output: Path,
    *,
    scene: str,
    video_id: str,
    frame_stride: int = 10,
    pixel_stride: int = 4,
    maximum_samples: int = 500_000,
    maximum_depth_metres: float = 20.0,
) -> dict:
    if frame_stride <= 0 or pixel_stride <= 0 or maximum_samples <= 0:
        raise ValueError("frame/pixel strides and maximum samples must be positive")
    if maximum_depth_metres <= 0.0 or not math.isfinite(maximum_depth_metres):
        raise ValueError("maximum depth must be finite and positive")

    output.parent.mkdir(parents=True, exist_ok=True)
    emitted = 0
    selected_frames = 0
    complete_frames = 0
    with tarfile.open(archive_path, "r:*") as archive, output.open("w", encoding="utf-8") as stream:
        frames = discover_frames(archive, video_id)
        complete_frames = len(frames)
        for frame_index in range(0, len(frames), frame_stride):
            frame = frames[frame_index]
            selected_frames += 1
            arkit_depth = decode_image(read_member(archive, frame.members["wide/depth"]))
            confidence = decode_image(read_member(archive, frame.members["wide/depth/confidence"]))
            gt_depth = decode_image(read_member(archive, frame.members["gt/depth"]))
            arkit_k = parse_intrinsics(read_member(archive, frame.members["wide/depth/k"]))
            gt_k = parse_intrinsics(read_member(archive, frame.members["gt/depth/k"]))
            for row in sample_frame(
                scene=scene,
                frame=frame,
                arkit_depth=arkit_depth,
                confidence=confidence,
                gt_depth=gt_depth,
                arkit_k=arkit_k,
                gt_k=gt_k,
                pixel_stride=pixel_stride,
                maximum_depth_metres=maximum_depth_metres,
            ):
                stream.write(json.dumps(row, sort_keys=True) + "\n")
                emitted += 1
                if emitted >= maximum_samples:
                    break
            if emitted >= maximum_samples:
                break

    if emitted == 0:
        raise ValueError("CA-1M archive produced no valid ARKit-vs-FARO depth samples")
    metadata = {
        "schemaVersion": 1,
        "scene": scene,
        "videoId": video_id,
        "archive": str(archive_path.resolve()),
        "archiveSha256": sha256_file(archive_path),
        "output": str(output.resolve()),
        "outputSha256": sha256_file(output),
        "completeFrames": complete_frames,
        "selectedFrames": selected_frames,
        "emittedSamples": emitted,
        "frameStride": frame_stride,
        "pixelStride": pixel_stride,
        "maximumSamples": maximum_samples,
        "maximumDepthMetres": maximum_depth_metres,
        "observationSource": "onboard ARKit LiDAR depth",
        "groundTruthSource": "FARO laser-scanner rendered depth",
        "correspondence": "camera ray mapped using released ARKit-depth and GT-depth intrinsics",
    }
    metadata_path = output.with_suffix(output.suffix + ".meta.json")
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--scene", required=True)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frame-stride", type=int, default=10)
    parser.add_argument("--pixel-stride", type=int, default=4)
    parser.add_argument("--max-samples", type=int, default=500_000)
    parser.add_argument("--max-depth", type=float, default=20.0)
    args = parser.parse_args()
    try:
        metadata = generate_samples(
            args.archive.resolve(),
            args.output.resolve(),
            scene=args.scene,
            video_id=args.video_id,
            frame_stride=args.frame_stride,
            pixel_stride=args.pixel_stride,
            maximum_samples=args.max_samples,
            maximum_depth_metres=args.max_depth,
        )
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError, tarfile.TarError) as exc:
        print(f"ca1m_uncertainty_samples: {exc}")
        return 2
    print(json.dumps({"ok": True, **metadata}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
