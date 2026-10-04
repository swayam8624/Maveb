#!/usr/bin/env python3
"""Validate/index the public VG-Scene evolving RGB-D benchmark without copying dataset bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

REAL_REQUIRED = ("rgb.txt", "depth.txt", "groundtruth.txt")
SYNTHETIC_REQUIRED = ("intrinsic.txt", "traj.txt")
SEQUENCE_SUFFIX = re.compile(r"^(?P<name>.+)_(?P<change>\d+)$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def data_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def parse_tum_list(path: Path) -> list[tuple[float, str]]:
    rows: list[tuple[float, str]] = []
    last = float("-inf")
    for number, line in enumerate(data_lines(path), 1):
        parts = line.split()
        if len(parts) < 2:
            raise ValueError(f"{path}:{number}: expected timestamp and relative path")
        timestamp = float(parts[0])
        if timestamp <= last:
            raise ValueError(f"{path}:{number}: timestamps must increase strictly")
        last = timestamp
        rows.append((timestamp, parts[1]))
    if not rows:
        raise ValueError(f"{path}: no records")
    return rows


def validate_real(sequence: Path, change_start: int) -> dict[str, Any]:
    for name in REAL_REQUIRED:
        if not (sequence / name).is_file():
            raise ValueError(f"{sequence}: missing {name}")
    rgb = parse_tum_list(sequence / "rgb.txt")
    depth = parse_tum_list(sequence / "depth.txt")
    if len(rgb) != len(depth):
        raise ValueError(f"{sequence}: RGB/depth list lengths differ")
    for (_, rgb_rel), (_, depth_rel) in zip(rgb, depth, strict=True):
        if not (sequence / rgb_rel).is_file():
            raise ValueError(f"{sequence}: missing RGB frame {rgb_rel}")
        if not (sequence / depth_rel).is_file():
            raise ValueError(f"{sequence}: missing depth frame {depth_rel}")
    poses = data_lines(sequence / "groundtruth.txt")
    if not poses:
        raise ValueError(f"{sequence}: empty groundtruth.txt")
    if change_start <= 0 or change_start >= len(rgb):
        raise ValueError(
            f"{sequence}: change-start frame {change_start} is outside {len(rgb)} RGB-D frames"
        )
    return {
        "format": "tum-rgbd",
        "frameCount": len(rgb),
        "changeStartFrame": change_start,
        "preChangeFrames": change_start,
        "postChangeFrames": len(rgb) - change_start,
        "metadataHashes": {
            name: sha256(sequence / name) for name in REAL_REQUIRED
        },
    }


def numbered_files(directory: Path, prefix: str, suffixes: tuple[str, ...]) -> dict[int, Path]:
    result: dict[int, Path] = {}
    for path in sorted(directory.iterdir()):
        if not path.is_file() or not path.name.startswith(prefix):
            continue
        if path.suffix.lower() not in suffixes:
            continue
        digits = path.stem[len(prefix):]
        if not digits.isdigit():
            continue
        result[int(digits)] = path
    return result


def validate_synthetic(sequence: Path, change_start: int) -> dict[str, Any]:
    for name in SYNTHETIC_REQUIRED:
        if not (sequence / name).is_file():
            raise ValueError(f"{sequence}: missing {name}")
    results = sequence / "results"
    if not results.is_dir():
        raise ValueError(f"{sequence}: missing results directory")
    rgb = numbered_files(results, "frame", (".jpg", ".jpeg", ".png"))
    depth = numbered_files(results, "depth", (".png", ".exr"))
    if not rgb or set(rgb) != set(depth):
        raise ValueError(f"{sequence}: RGB/depth numbered frame sets differ or are empty")
    frame_ids = sorted(rgb)
    if frame_ids != list(range(frame_ids[0], frame_ids[0] + len(frame_ids))):
        raise ValueError(f"{sequence}: frame numbering is not contiguous")
    if change_start <= 0 or change_start >= len(frame_ids):
        raise ValueError(
            f"{sequence}: change-start frame {change_start} is outside {len(frame_ids)} frames"
        )
    return {
        "format": "replica-style",
        "frameCount": len(frame_ids),
        "firstFrameId": frame_ids[0],
        "changeStartFrame": change_start,
        "preChangeFrames": change_start,
        "postChangeFrames": len(frame_ids) - change_start,
        "metadataHashes": {
            name: sha256(sequence / name) for name in SYNTHETIC_REQUIRED
        },
    }


def discover(root: Path) -> dict[str, Any]:
    if not root.is_dir():
        raise ValueError(f"VG-Scene root does not exist: {root}")
    sequence_dirs = [
        path
        for path in root.rglob("*")
        if path.is_dir() and SEQUENCE_SUFFIX.match(path.name)
    ]
    rows = []
    for sequence in sorted(sequence_dirs):
        match = SEQUENCE_SUFFIX.match(sequence.name)
        assert match is not None
        change_start = int(match.group("change"))
        relative = sequence.relative_to(root).as_posix()
        if all((sequence / name).is_file() for name in REAL_REQUIRED):
            details = validate_real(sequence, change_start)
            source_kind = "real"
        elif all((sequence / name).is_file() for name in SYNTHETIC_REQUIRED):
            details = validate_synthetic(sequence, change_start)
            source_kind = "synthetic"
        else:
            continue
        rows.append(
            {
                "id": sequence.name,
                "relativePath": relative,
                "sourceKind": source_kind,
                **details,
            }
        )
    if not rows:
        raise ValueError("no valid VG-Scene sequences found")
    return {
        "schemaVersion": 1,
        "dataset": "VG-Scene",
        "sequenceCount": len(rows),
        "sequences": rows,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_json(args.output, discover(args.root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
