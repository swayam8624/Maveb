#!/usr/bin/env python3
"""Generate metric uncertainty observations from CA-1M depth and ARKitScenes sidecars.

CA-1M supplies onboard ARKit LiDAR depth and independently rendered FARO laser-scanner depth for the
same oriented camera frame. ARKitScenes raw supplies the confidence signal. Because the raw sidecar
may retain a different discrete image orientation than the CA-1M frame, raw `lowres_depth` is used
only as an orientation witness: for every sampled frame we choose the dihedral image transform that
best matches CA-1M's ARKit depth, then apply that exact transform to confidence.

No interpolation is used for confidence. CA-1M and FARO depth correspondence is still performed by
calibrated camera ray using their separate released intrinsics.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass
import hashlib
import io
import json
import math
from pathlib import Path
import tarfile
from typing import Iterator


REQUIRED_SUFFIXES = {"wide/depth", "wide/depth/k", "gt/depth", "gt/depth/k"}
MM_TO_M = 1000.0
NS_TO_S = 1_000_000_000.0


@dataclass(frozen=True)
class FrameMembers:
    video_id: str
    timestamp: str
    members: dict[str, tarfile.TarInfo]


@dataclass(frozen=True)
class SidecarFrame:
    timestamp_seconds: float
    path: Path


@dataclass(frozen=True)
class OrientationMatch:
    transform: str
    median_abs_error_mm: float
    p90_abs_error_mm: float
    valid_pixels: int


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_sha256(paths: set[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda value: str(value)):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


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
    if not frames:
        raise ValueError("archive contains no complete CA-1M ARKit-depth/FARO-depth frames")
    return frames


def parse_sidecar_timestamp(path: Path, video_id: str) -> float | None:
    prefix = f"{video_id}_"
    if path.suffix.lower() != ".png" or not path.stem.startswith(prefix):
        return None
    try:
        value = float(path.stem[len(prefix) :])
    except ValueError:
        return None
    if not math.isfinite(value) or value < 0.0:
        return None
    return value


def parse_confidence_timestamp(path: Path, video_id: str) -> float | None:
    return parse_sidecar_timestamp(path, video_id)


def discover_sidecar_frames(root: Path, video_id: str, label: str) -> list[SidecarFrame]:
    frames = []
    for path in root.rglob("*.png"):
        timestamp = parse_sidecar_timestamp(path, video_id)
        if timestamp is not None:
            frames.append(SidecarFrame(timestamp, path))
    frames.sort(key=lambda frame: frame.timestamp_seconds)
    if not frames:
        raise ValueError(f"no ARKitScenes {label} PNGs for video {video_id} under {root}")
    for previous, current in zip(frames, frames[1:]):
        if current.timestamp_seconds == previous.timestamp_seconds:
            raise ValueError(f"duplicate ARKitScenes {label} timestamp {current.timestamp_seconds}")
    return frames


def discover_confidence_frames(root: Path, video_id: str) -> list[SidecarFrame]:
    return discover_sidecar_frames(root, video_id, "confidence")


def nearest_sidecar_frame(
    frames: list[SidecarFrame], timestamp_seconds: float, maximum_delta_seconds: float
) -> tuple[SidecarFrame, float] | None:
    times = [frame.timestamp_seconds for frame in frames]
    index = bisect_left(times, timestamp_seconds)
    candidates = []
    if index < len(frames):
        candidates.append(frames[index])
    if index > 0:
        candidates.append(frames[index - 1])
    if not candidates:
        return None
    selected = min(candidates, key=lambda frame: abs(frame.timestamp_seconds - timestamp_seconds))
    delta = abs(selected.timestamp_seconds - timestamp_seconds)
    if delta > maximum_delta_seconds:
        return None
    return selected, delta


def nearest_confidence_frame(
    frames: list[SidecarFrame], timestamp_seconds: float, maximum_delta_seconds: float
) -> tuple[SidecarFrame, float] | None:
    return nearest_sidecar_frame(frames, timestamp_seconds, maximum_delta_seconds)


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
            flat.extend(value if isinstance(value, list) else [value])
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
        raise ValueError(f"expected a single-channel depth/confidence image, got {image.shape}")
    return image


def apply_discrete_transform(image, transform: str):
    import numpy as np

    if transform == "identity":
        return image
    if transform == "rot90-ccw":
        return np.rot90(image, 1)
    if transform == "rot180":
        return np.rot90(image, 2)
    if transform == "rot90-cw":
        return np.rot90(image, -1)
    if transform == "flip-lr":
        return np.fliplr(image)
    if transform == "flip-ud":
        return np.flipud(image)
    if transform == "transpose":
        return image.T
    if transform == "transverse":
        return np.flipud(np.fliplr(image.T))
    raise ValueError(f"unknown sidecar transform: {transform}")


def infer_orientation_transform(raw_depth, ca1m_depth, minimum_valid_pixels: int = 256) -> OrientationMatch:
    import numpy as np

    candidates = (
        "identity",
        "rot90-ccw",
        "rot180",
        "rot90-cw",
        "flip-lr",
        "flip-ud",
        "transpose",
        "transverse",
    )
    scored: list[OrientationMatch] = []
    for name in candidates:
        transformed = apply_discrete_transform(raw_depth, name)
        if transformed.shape != ca1m_depth.shape:
            continue
        valid = (transformed > 0) & (ca1m_depth > 0)
        count = int(np.count_nonzero(valid))
        if count < minimum_valid_pixels:
            continue
        errors = np.abs(transformed[valid].astype(np.float64) - ca1m_depth[valid].astype(np.float64))
        scored.append(
            OrientationMatch(
                transform=name,
                median_abs_error_mm=float(np.median(errors)),
                p90_abs_error_mm=float(np.percentile(errors, 90.0)),
                valid_pixels=count,
            )
        )
    if not scored:
        raise ValueError(
            f"unable to orient ARKitScenes lowres_depth {raw_depth.shape} to CA-1M depth {ca1m_depth.shape}"
        )
    scored.sort(key=lambda item: (item.median_abs_error_mm, item.p90_abs_error_mm, -item.valid_pixels, item.transform))
    return scored[0]


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


def confidence_level(raw) -> int:
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError("ARKitScenes confidence must be finite")
    rounded = int(round(value))
    if abs(value - rounded) > 1e-6 or rounded not in (0, 1, 2):
        raise ValueError(f"ARKitScenes confidence must use documented uint8 levels 0/1/2, got {value}")
    return rounded


def confidence_value(raw) -> float:
    return confidence_level(raw) / 2.0


def sample_frame(
    *,
    scene: str,
    frame: FrameMembers,
    arkit_depth,
    confidence,
    confidence_timestamp_seconds: float,
    confidence_delta_seconds: float,
    witness_timestamp_seconds: float,
    witness_delta_seconds: float,
    orientation: OrientationMatch,
    gt_depth,
    arkit_k: tuple[float, float, float, float],
    gt_k: tuple[float, float, float, float],
    pixel_stride: int,
    maximum_depth_metres: float,
) -> Iterator[dict]:
    if arkit_depth.shape != confidence.shape:
        raise ValueError(
            f"oriented confidence shape {confidence.shape} still differs from ARKit depth {arkit_depth.shape}"
        )
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
            raw_confidence = confidence_level(confidence[y, x])
            yield {
                "scene": scene,
                "sampleId": f"{frame.video_id}-{frame.timestamp}-x{x}-y{y}",
                "videoId": frame.video_id,
                "timestampNanoseconds": int(frame.timestamp),
                "confidenceTimestampSeconds": confidence_timestamp_seconds,
                "confidenceJoinDeltaMilliseconds": confidence_delta_seconds * 1000.0,
                "orientationWitnessTimestampSeconds": witness_timestamp_seconds,
                "orientationWitnessJoinDeltaMilliseconds": witness_delta_seconds * 1000.0,
                "sidecarOrientationTransform": orientation.transform,
                "orientationWitnessMedianAbsErrorMillimetres": orientation.median_abs_error_mm,
                "orientationWitnessP90AbsErrorMillimetres": orientation.p90_abs_error_mm,
                "orientationWitnessValidPixels": orientation.valid_pixels,
                "pixelX": x,
                "pixelY": y,
                "gtPixelX": gxi,
                "gtPixelY": gyi,
                "depthMetres": observed,
                "referenceDepthMetres": reference,
                "signedErrorMetres": observed - reference,
                "rawSensorConfidenceLevel": raw_confidence,
                "sensorConfidence": raw_confidence / 2.0,
                "confidenceSource": "ARKitScenes raw confidence uint8 0/1/2; normalized as level/2",
                "poseConfidence": 1.0,
                "reprojectionErrorPixels": 0.0,
                "focalLengthPixels": focal,
                "alignmentPositionRmseMetres": 0.0,
                "alignmentOrientationErrorDegrees": 0.0,
                "groundTruthSource": "CA-1M FARO laser-scanner rendered depth",
            }


def generate_samples(
    archive_path: Path,
    confidence_root: Path,
    lowres_depth_root: Path,
    output: Path,
    *,
    scene: str,
    video_id: str,
    frame_stride: int = 10,
    pixel_stride: int = 4,
    maximum_samples: int = 500_000,
    maximum_depth_metres: float = 20.0,
    maximum_sidecar_delta_seconds: float = 0.020,
) -> dict:
    if frame_stride <= 0 or pixel_stride <= 0 or maximum_samples <= 0:
        raise ValueError("frame/pixel strides and maximum samples must be positive")
    if maximum_depth_metres <= 0.0 or not math.isfinite(maximum_depth_metres):
        raise ValueError("maximum depth must be finite and positive")
    if maximum_sidecar_delta_seconds <= 0.0 or not math.isfinite(maximum_sidecar_delta_seconds):
        raise ValueError("sidecar timestamp tolerance must be finite and positive")

    confidence_frames = discover_sidecar_frames(confidence_root, video_id, "confidence")
    witness_frames = discover_sidecar_frames(lowres_depth_root, video_id, "lowres_depth")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(output.suffix + ".tmp")
    temporary_output.unlink(missing_ok=True)

    emitted = selected_frames = matched_frames = skipped_frames_no_sidecar = complete_frames = 0
    max_conf_delta = max_witness_delta = max_witness_median_mm = 0.0
    used_confidence_paths: set[Path] = set()
    used_witness_paths: set[Path] = set()
    transform_counts: Counter[str] = Counter()

    try:
        with tarfile.open(archive_path, "r:*") as archive, temporary_output.open("w", encoding="utf-8") as stream:
            frames = discover_frames(archive, video_id)
            complete_frames = len(frames)
            for frame_index in range(0, len(frames), frame_stride):
                frame = frames[frame_index]
                selected_frames += 1
                timestamp_seconds = int(frame.timestamp) / NS_TO_S
                confidence_match = nearest_sidecar_frame(
                    confidence_frames, timestamp_seconds, maximum_sidecar_delta_seconds
                )
                witness_match = nearest_sidecar_frame(
                    witness_frames, timestamp_seconds, maximum_sidecar_delta_seconds
                )
                if confidence_match is None or witness_match is None:
                    skipped_frames_no_sidecar += 1
                    continue
                confidence_frame, confidence_delta = confidence_match
                witness_frame, witness_delta = witness_match

                arkit_depth = decode_image(read_member(archive, frame.members["wide/depth"]))
                raw_confidence = decode_image(confidence_frame.path.read_bytes())
                raw_witness_depth = decode_image(witness_frame.path.read_bytes())
                orientation = infer_orientation_transform(raw_witness_depth, arkit_depth)
                confidence = apply_discrete_transform(raw_confidence, orientation.transform)
                if confidence.shape != arkit_depth.shape:
                    raise ValueError(
                        f"confidence transform {orientation.transform} produced {confidence.shape}, "
                        f"expected {arkit_depth.shape}"
                    )

                gt_depth = decode_image(read_member(archive, frame.members["gt/depth"]))
                arkit_k = parse_intrinsics(read_member(archive, frame.members["wide/depth/k"]))
                gt_k = parse_intrinsics(read_member(archive, frame.members["gt/depth/k"]))
                matched_frames += 1
                used_confidence_paths.add(confidence_frame.path)
                used_witness_paths.add(witness_frame.path)
                transform_counts[orientation.transform] += 1
                max_conf_delta = max(max_conf_delta, confidence_delta)
                max_witness_delta = max(max_witness_delta, witness_delta)
                max_witness_median_mm = max(max_witness_median_mm, orientation.median_abs_error_mm)

                for row in sample_frame(
                    scene=scene,
                    frame=frame,
                    arkit_depth=arkit_depth,
                    confidence=confidence,
                    confidence_timestamp_seconds=confidence_frame.timestamp_seconds,
                    confidence_delta_seconds=confidence_delta,
                    witness_timestamp_seconds=witness_frame.timestamp_seconds,
                    witness_delta_seconds=witness_delta,
                    orientation=orientation,
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
            raise ValueError("CA-1M/ARKitScenes join produced no valid ARKit-vs-FARO depth samples")
        temporary_output.replace(output)
    except Exception:
        temporary_output.unlink(missing_ok=True)
        raise

    metadata = {
        "schemaVersion": 3,
        "scene": scene,
        "videoId": video_id,
        "archive": str(archive_path.resolve()),
        "archiveSha256": sha256_file(archive_path),
        "confidenceRoot": str(confidence_root.resolve()),
        "lowresDepthRoot": str(lowres_depth_root.resolve()),
        "confidenceFilesDiscovered": len(confidence_frames),
        "lowresDepthFilesDiscovered": len(witness_frames),
        "confidenceFilesUsed": len(used_confidence_paths),
        "lowresDepthFilesUsed": len(used_witness_paths),
        "confidenceManifestSha256": manifest_sha256(used_confidence_paths),
        "orientationWitnessManifestSha256": manifest_sha256(used_witness_paths),
        "sidecarTransformCounts": dict(sorted(transform_counts.items())),
        "maximumOrientationWitnessMedianAbsErrorMillimetres": max_witness_median_mm,
        "output": str(output.resolve()),
        "outputSha256": sha256_file(output),
        "completeFrames": complete_frames,
        "selectedFrames": selected_frames,
        "matchedSidecarFrames": matched_frames,
        "matchedConfidenceFrames": matched_frames,
        "skippedFramesNoSidecar": skipped_frames_no_sidecar,
        "skippedFramesNoConfidence": skipped_frames_no_sidecar,
        "emittedSamples": emitted,
        "frameStride": frame_stride,
        "pixelStride": pixel_stride,
        "maximumSamples": maximum_samples,
        "maximumDepthMetres": maximum_depth_metres,
        "maximumSidecarDeltaMilliseconds": maximum_sidecar_delta_seconds * 1000.0,
        "maximumObservedConfidenceDeltaMilliseconds": max_conf_delta * 1000.0,
        "maximumObservedOrientationWitnessDeltaMilliseconds": max_witness_delta * 1000.0,
        "observationSource": "CA-1M onboard ARKit LiDAR depth",
        "confidenceSource": "ARKitScenes raw confidence uint8 0/1/2",
        "orientationWitness": "ARKitScenes raw lowres_depth; used only to select a discrete image transform",
        "confidenceNormalization": "sensorConfidence = rawSensorConfidenceLevel / 2",
        "groundTruthSource": "CA-1M FARO laser-scanner rendered depth",
        "depthCorrespondence": "camera ray mapped using released ARKit-depth and GT-depth intrinsics",
    }
    metadata_path = output.with_suffix(output.suffix + ".meta.json")
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--confidence-root", type=Path, required=True)
    parser.add_argument("--lowres-depth-root", type=Path, required=True)
    parser.add_argument("--scene", required=True)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frame-stride", type=int, default=10)
    parser.add_argument("--pixel-stride", type=int, default=4)
    parser.add_argument("--max-samples", type=int, default=500_000)
    parser.add_argument("--max-depth", type=float, default=20.0)
    parser.add_argument("--confidence-max-delta-ms", type=float, default=20.0)
    args = parser.parse_args()
    try:
        metadata = generate_samples(
            args.archive.resolve(),
            args.confidence_root.resolve(),
            args.lowres_depth_root.resolve(),
            args.output.resolve(),
            scene=args.scene,
            video_id=args.video_id,
            frame_stride=args.frame_stride,
            pixel_stride=args.pixel_stride,
            maximum_samples=args.max_samples,
            maximum_depth_metres=args.max_depth,
            maximum_sidecar_delta_seconds=args.confidence_max_delta_ms / 1000.0,
        )
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError, tarfile.TarError) as exc:
        print(f"ca1m_uncertainty_samples: {exc}")
        return 2
    print(json.dumps({"ok": True, **metadata}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
