#!/usr/bin/env python3
"""Build a deterministic COLMAP + recorded-RGB-D alignment fixture and exercise the CLI."""

from __future__ import annotations

import json
import math
import pathlib
import struct
import subprocess
import sys


POSITIONS = [
    (-1.2, -0.5, 0.1),
    (-0.8, 0.4, 0.3),
    (-0.2, -0.9, 0.6),
    (0.3, 0.8, -0.2),
    (0.9, -0.4, 0.9),
    (1.3, 0.5, 0.2),
    (-0.7, 1.1, -0.6),
    (0.1, 1.4, 0.7),
    (0.8, 1.0, -0.8),
    (1.5, -1.1, 0.4),
    (-1.4, 0.7, 1.0),
    (0.5, -1.3, -0.7),
]


def axis_angle(axis: tuple[float, float, float], degrees: float) -> tuple[float, ...]:
    magnitude = math.sqrt(sum(component * component for component in axis))
    half = math.radians(degrees) / 2.0
    sine = math.sin(half) / magnitude
    return (math.cos(half), axis[0] * sine, axis[1] * sine, axis[2] * sine)


def multiply(left: tuple[float, ...], right: tuple[float, ...]) -> tuple[float, ...]:
    w1, x1, y1, z1 = left
    w2, x2, y2, z2 = right
    return (
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    )


def conjugate(quaternion: tuple[float, ...]) -> tuple[float, ...]:
    return (quaternion[0], -quaternion[1], -quaternion[2], -quaternion[3])


def rotate(quaternion: tuple[float, ...], point: tuple[float, ...]) -> tuple[float, ...]:
    rotated = multiply(multiply(quaternion, (0.0, *point)), conjugate(quaternion))
    return rotated[1:]


def transform(
    point: tuple[float, ...],
    scale: float,
    rotation: tuple[float, ...],
    translation: tuple[float, ...],
) -> tuple[float, ...]:
    rotated = rotate(rotation, point)
    return tuple(scale * rotated[index] + translation[index] for index in range(3))


def run(*arguments: str, success: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(arguments, capture_output=True, check=False, text=True)
    if success and result.returncode != 0:
        raise AssertionError(
            f"command failed ({result.returncode}): {' '.join(arguments)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    if not success and result.returncode == 0:
        raise AssertionError(f"command unexpectedly succeeded: {' '.join(arguments)}")
    return result


def create_fixture(root: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    model = root / "colmap"
    capture = root / "capture.mavebcapture"
    model.mkdir(parents=True, exist_ok=True)
    capture.mkdir(parents=True, exist_ok=True)
    (capture / "color.rgb8").write_bytes(b"\x20\x40\x80")
    (capture / "depth.f32").write_bytes(struct.pack("<f", 1.0))

    alignment_rotation = axis_angle((0.2, -0.3, 0.4), 37.0)
    scale = 2.35
    translation = (1.4, -0.7, 2.2)
    frames: list[dict[str, object]] = []
    pairs: list[dict[str, object]] = []
    lines = ["# Synthetic COLMAP camera rig with spaces in image names"]
    for index, position in enumerate(POSITIONS):
        source_orientation = axis_angle((0.0, 1.0, 0.0), float(index * 7))
        world_to_camera = conjugate(source_orientation)
        translated = rotate(world_to_camera, position)
        colmap_translation = tuple(-component for component in translated)
        image_name = f"ipad/frame {index:02d}.jpg"
        lines.append(
            f"{index + 1} {' '.join(format(value, '.17g') for value in world_to_camera)} "
            f"{' '.join(format(value, '.17g') for value in colmap_translation)} 1 {image_name}"
        )
        lines.append("")

        target_position = transform(position, scale, alignment_rotation, translation)
        target_position = (
            target_position[0] + ((index % 3) - 1) * 0.0008,
            target_position[1] + (index % 2) * 0.0005,
            target_position[2],
        )
        target_orientation = multiply(alignment_rotation, source_orientation)
        if index == 3:
            target_position = (4.0, -3.0, 2.0)
            target_orientation = axis_angle((1.0, 0.0, 0.0), 120.0)
        if index == 9:
            target_position = (-5.0, 1.0, -4.0)
            target_orientation = axis_angle((0.0, 0.0, 1.0), 150.0)
        frames.append(
            {
                "frameId": index + 1,
                "timestampNs": (index + 1) * 1_000_000,
                "color": "color.rgb8",
                "depth": "depth.f32",
                "orientation": target_orientation,
                "translation": target_position,
            }
        )
        pairs.append({"colmapImage": image_name, "captureFrameId": index + 1})

    (model / "images.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest = {
        "schemaVersion": 1,
        "sourceId": "synthetic-ipad-metric-rig",
        "calibration": {"width": 1, "height": 1, "fx": 1.0, "fy": 1.0, "cx": 0.0, "cy": 0.0},
        "frames": frames,
    }
    (capture / "manifest.json").write_text(
        json.dumps(manifest, separators=(",", ":")), encoding="utf-8"
    )
    matches = root / "matches.json"
    matches.write_text(
        json.dumps({"schemaVersion": 1, "pairs": pairs}, separators=(",", ":")),
        encoding="utf-8",
    )
    return model, capture, matches


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: assert-sensor-alignment.py <cli> <artifact-directory>")
    executable = pathlib.Path(sys.argv[1])
    artifacts = pathlib.Path(sys.argv[2])
    artifacts.mkdir(parents=True, exist_ok=True)
    model, capture, matches = create_fixture(artifacts / "fixture")
    first = artifacts / "metric-rig-first.json"
    second = artifacts / "metric-rig-second.json"
    first.unlink(missing_ok=True)
    second.unlink(missing_ok=True)

    first_result = run(
        str(executable),
        str(model),
        str(capture),
        "--matches",
        str(matches),
        "--output",
        str(first),
        "--json",
    )
    summary = json.loads(first_result.stdout)
    report = json.loads(first.read_text(encoding="utf-8"))
    assert summary["ok"] is True and summary["accepted"] is True
    assert report["accepted"] is True
    assert report["metrics"]["correspondences"] == 12
    assert report["metrics"]["inliers"] == 10
    assert abs(report["transform"]["scale"] - 2.35) < 0.002
    assert len(report["metricCameras"]) == 12
    assert report["metrics"]["positionP95Metres"] < 0.003

    run(
        str(executable),
        str(model),
        str(capture),
        "--matches",
        str(matches),
        "--output",
        str(second),
        "--json",
    )
    assert first.read_bytes() == second.read_bytes()

    sentinel = artifacts / "dry-run-sentinel.json"
    sentinel.write_text("unchanged", encoding="utf-8")
    dry_run = run(
        str(executable),
        str(model),
        str(capture),
        "--matches",
        str(matches),
        "--output",
        str(sentinel),
        "--dry-run",
        "--json",
    )
    assert json.loads(dry_run.stdout)["dryRun"] is True
    assert sentinel.read_text(encoding="utf-8") == "unchanged"

    rejected_quality = artifacts / "rejected-quality.json"
    rejected_quality.unlink(missing_ok=True)
    quality_result = run(
        str(executable),
        str(model),
        str(capture),
        "--matches",
        str(matches),
        "--output",
        str(rejected_quality),
        "--minimum-inlier-ratio",
        "0.9",
        "--json",
        success=False,
    )
    quality_summary = json.loads(quality_result.stdout)
    assert quality_summary["ok"] is True and quality_summary["accepted"] is False
    assert json.loads(rejected_quality.read_text(encoding="utf-8"))["accepted"] is False

    invalid_matches = artifacts / "invalid-matches.json"
    invalid_matches.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "pairs": [
                    {"colmapImage": "ipad/frame 00.jpg", "captureFrameId": 1},
                    {"colmapImage": "ipad/frame 01.jpg", "captureFrameId": 1},
                ],
            }
        ),
        encoding="utf-8",
    )
    invalid_output = artifacts / "must-not-exist.json"
    invalid_output.unlink(missing_ok=True)
    rejected = run(
        str(executable),
        str(model),
        str(capture),
        "--matches",
        str(invalid_matches),
        "--output",
        str(invalid_output),
        "--json",
        success=False,
    )
    assert json.loads(rejected.stderr)["ok"] is False
    assert not invalid_output.exists()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
