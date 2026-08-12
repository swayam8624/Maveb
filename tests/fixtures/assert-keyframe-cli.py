#!/usr/bin/env python3
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zlib


def write_gray_png(path: Path, variant: int) -> None:
    width = 64
    height = 64
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            if variant == 3:
                value = 128
            elif variant == 2:
                value = (y * 4) % 256
            else:
                value = ((x + variant * 16) * 4) % 256
            rows.append(value)

    def chunk(name: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + name
            + payload
            + struct.pack(">I", zlib.crc32(name + payload) & 0xFFFFFFFF)
        )

    encoded = b"\x89PNG\r\n\x1a\n"
    encoded += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
    encoded += chunk(b"IDAT", zlib.compress(bytes(rows), 9))
    encoded += chunk(b"IEND", b"")
    path.write_bytes(encoded)


def main() -> int:
    executable = Path(sys.argv[1])
    root = Path(sys.argv[2])
    shutil.rmtree(root, ignore_errors=True)
    frames = root / "frames"
    frames.mkdir(parents=True)
    for index, variant in enumerate((0, 1, 0, 1, 3, 2), 1):
        write_gray_png(frames / f"frame_{index:06d}.png", variant)
    output = root / "selection"
    result = subprocess.run(
        [str(executable), str(frames), "--output", str(output), "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    manifest = json.loads((output / "keyframes.json").read_text())
    assert manifest["valid"] is True
    assert manifest["selectedCount"] >= 3
    assert any(frame["reason"] == "near-duplicate" for frame in manifest["frames"])
    selected = (output / "selected-images.txt").read_text().splitlines()
    assert len(selected) == manifest["selectedCount"]
    assert all(not Path(item).is_absolute() for item in selected)
    (output / "stale.txt").write_text("old selection")
    replaced = subprocess.run(
        [str(executable), str(frames), "--output", str(output), "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert replaced.returncode == 0
    assert not (output / "stale.txt").exists()
    assert json.loads((output / "keyframes.json").read_text())["selectedCount"] == len(selected)

    for invalid in ("nan", "inf", "0.25junk"):
        rejected = subprocess.run(
            [
                str(executable),
                str(frames),
                "--output",
                str(output),
                "--relative-sharpness",
                invalid,
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert rejected.returncode != 0
        error = json.loads(rejected.stderr)
        assert error["ok"] is False
        assert error["error"]["message"] == "Selection threshold is invalid"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
