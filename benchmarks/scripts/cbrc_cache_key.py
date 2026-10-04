#!/usr/bin/env python3
"""Compute deterministic cache keys for broad CBRC campaign stages."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="maveb-broad-cache")
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--value", action="append", default=[])
    args = parser.parse_args()

    digest = hashlib.sha256()
    digest.update(args.label.encode("utf-8"))
    digest.update(b"\0")

    for raw in sorted(args.file):
        path = Path(raw).expanduser().resolve()
        if not path.is_file():
            raise SystemExit(f"cache-key input file missing: {path}")
        digest.update(b"file\0")
        digest.update(str(path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\0")

    for value in sorted(args.value):
        digest.update(b"value\0")
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")

    print(digest.hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
