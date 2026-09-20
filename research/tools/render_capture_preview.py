#!/usr/bin/env python3
"""Decode AetherBenchmark raw scientific captures and build deterministic previews/error maps.

No image library is required. Outputs are portable PPM/PGM files whose pixels are derived directly
from the raw Metal buffers. Tone mapping is for visualization only; the raw files remain the
scientific source of truth.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
from pathlib import Path
from typing import Iterable


def read_metadata(directory: Path) -> dict:
    data = json.loads((directory / "capture.json").read_text())
    if data.get("schemaVersion") != 1:
        raise ValueError("unsupported capture metadata schema")
    width = int(data["width"])
    height = int(data["height"])
    if width <= 0 or height <= 0:
        raise ValueError("invalid capture dimensions")
    return data


def read_half_rgba(path: Path, count: int) -> list[tuple[float, float, float, float]]:
    raw = path.read_bytes()
    expected = count * 8
    if len(raw) != expected:
        raise ValueError(f"{path}: expected {expected} bytes, got {len(raw)}")
    return list(struct.iter_unpack("<eeee", raw))


def read_float32(path: Path, count: int) -> tuple[float, ...]:
    raw = path.read_bytes()
    expected = count * 4
    if len(raw) != expected:
        raise ValueError(f"{path}: expected {expected} bytes, got {len(raw)}")
    return struct.unpack(f"<{count}f", raw)


def read_uint32(path: Path, count: int) -> tuple[int, ...]:
    raw = path.read_bytes()
    expected = count * 4
    if len(raw) != expected:
        raise ValueError(f"{path}: expected {expected} bytes, got {len(raw)}")
    return struct.unpack(f"<{count}I", raw)


def aces(value: float) -> float:
    value = max(value, 0.0)
    a, b, c, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
    return min(max((value * (a * value + b)) / (value * (c * value + d) + e), 0.0), 1.0)


def srgb(value: float) -> float:
    value = min(max(value, 0.0), 1.0)
    return 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1.0 / 2.4) - 0.055


def rgb8(color: Iterable[float], exposure_stops: float = 0.0) -> bytes:
    scale = 2.0 ** exposure_stops
    channels = []
    for value in list(color)[:3]:
        finite = value if math.isfinite(value) else 0.0
        channels.append(round(srgb(aces(finite * scale)) * 255.0))
    return bytes(channels)


def write_ppm(path: Path, width: int, height: int, pixels: bytes) -> None:
    if len(pixels) != width * height * 3:
        raise ValueError("PPM pixel payload length mismatch")
    path.write_bytes(f"P6\n{width} {height}\n255\n".encode() + pixels)


def write_pgm16(path: Path, width: int, height: int, values: Iterable[int]) -> None:
    payload = bytearray()
    for value in values:
        value = min(max(int(value), 0), 65535)
        payload.extend(struct.pack(">H", value))
    if len(payload) != width * height * 2:
        raise ValueError("PGM pixel payload length mismatch")
    path.write_bytes(f"P5\n{width} {height}\n65535\n".encode() + payload)


def finite_depth_range(depth: tuple[float, ...]) -> tuple[float, float]:
    valid = sorted(value for value in depth if math.isfinite(value) and value > 0.0)
    if not valid:
        return 0.0, 1.0
    low = valid[max(0, int(len(valid) * 0.01) - 1)]
    high = valid[min(len(valid) - 1, int(len(valid) * 0.99))]
    if high <= low:
        high = low + 1.0
    return low, high


def convert(directory: Path, output: Path, exposure: float) -> dict:
    meta = read_metadata(directory)
    width, height = int(meta["width"]), int(meta["height"])
    count = width * height
    color = read_half_rgba(directory / "color.rgba16f", count)
    depth = read_float32(directory / "depth.r32f", count)
    ids = read_uint32(directory / "ids.r32u", count)

    output.mkdir(parents=True, exist_ok=True)
    color_pixels = b"".join(rgb8(pixel, exposure) for pixel in color)
    write_ppm(output / "color.ppm", width, height, color_pixels)

    low, high = finite_depth_range(depth)
    depth_values = []
    for value in depth:
        if not math.isfinite(value) or value <= 0.0:
            depth_values.append(0)
        else:
            normalized = min(max((value - low) / (high - low), 0.0), 1.0)
            depth_values.append(round((1.0 - normalized) * 65535.0))
    write_pgm16(output / "depth.pgm", width, height, depth_values)

    # Stable multiplicative hash maps 32-bit source IDs to a 16-bit diagnostic grayscale.
    id_values = [0 if value == 0 else ((value * 40503) ^ (value >> 7)) & 0xFFFF for value in ids]
    write_pgm16(output / "ids.pgm", width, height, id_values)

    result = {
        "schemaVersion": 1,
        "source": str(directory),
        "width": width,
        "height": height,
        "exposureStops": exposure,
        "depthPreviewRange": [low, high],
        "nonzeroIds": sum(value != 0 for value in ids),
    }
    (output / "preview.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def compare(reference: Path, candidate: Path, output: Path, scale: float) -> dict:
    reference_meta = read_metadata(reference)
    candidate_meta = read_metadata(candidate)
    if (reference_meta["width"], reference_meta["height"]) != (
        candidate_meta["width"],
        candidate_meta["height"],
    ):
        raise ValueError("capture dimensions differ")
    width, height = int(reference_meta["width"]), int(reference_meta["height"])
    count = width * height
    ref = read_half_rgba(reference / "color.rgba16f", count)
    cand = read_half_rgba(candidate / "color.rgba16f", count)

    squared = 0.0
    absolute = 0.0
    maximum = 0.0
    error_pixels = bytearray()
    for a, b in zip(ref, cand, strict=True):
        channel_errors = [
            abs((b[i] if math.isfinite(b[i]) else 0.0) - (a[i] if math.isfinite(a[i]) else 0.0))
            for i in range(3)
        ]
        absolute += sum(channel_errors)
        squared += sum(value * value for value in channel_errors)
        maximum = max(maximum, *channel_errors)
        visual = min(max(max(channel_errors) * scale, 0.0), 1.0)
        byte = round(visual * 255.0)
        error_pixels.extend((byte, byte, byte))

    samples = count * 3
    output.mkdir(parents=True, exist_ok=True)
    write_ppm(output / "color-absolute-error.ppm", width, height, bytes(error_pixels))
    result = {
        "schemaVersion": 1,
        "reference": str(reference),
        "candidate": str(candidate),
        "width": width,
        "height": height,
        "meanAbsoluteRgb": absolute / samples,
        "rmseRgb": math.sqrt(squared / samples),
        "maximumAbsoluteRgb": maximum,
        "visualScale": scale,
    }
    (output / "comparison.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    preview = subparsers.add_parser("preview")
    preview.add_argument("capture", type=Path)
    preview.add_argument("--output", type=Path, required=True)
    preview.add_argument("--exposure", type=float, default=0.0)

    comparison = subparsers.add_parser("compare")
    comparison.add_argument("reference", type=Path)
    comparison.add_argument("candidate", type=Path)
    comparison.add_argument("--output", type=Path, required=True)
    comparison.add_argument("--visual-scale", type=float, default=8.0)

    args = parser.parse_args()
    if args.command == "preview":
        convert(args.capture, args.output, args.exposure)
    else:
        compare(args.reference, args.candidate, args.output, args.visual_scale)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
