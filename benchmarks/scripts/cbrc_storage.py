#!/usr/bin/env python3
"""Disk-safe materialization helpers for CBRC campaigns."""

from __future__ import annotations

import ctypes
import errno
import os
import shutil
import sys
from pathlib import Path


def _clonefile_macos(source: Path, destination: Path) -> bool:
    if sys.platform != "darwin":
        return False
    libc = ctypes.CDLL(None, use_errno=True)
    clonefile = getattr(libc, "clonefile", None)
    if clonefile is None:
        return False
    clonefile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
    clonefile.restype = ctypes.c_int
    result = clonefile(
        os.fsencode(source),
        os.fsencode(destination),
        0,
    )
    if result == 0:
        return True
    value = ctypes.get_errno()
    if value in {
        errno.EXDEV,
        errno.ENOTSUP,
        getattr(errno, "EOPNOTSUPP", errno.ENOTSUP),
        errno.ENOSYS,
        errno.EINVAL,
    }:
        return False
    raise OSError(value, os.strerror(value), str(destination))


def _reflink_linux(source: Path, destination: Path) -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        import fcntl
    except ImportError:
        return False
    ficlone = 0x40049409
    try:
        with source.open("rb") as src, destination.open("xb") as dst:
            fcntl.ioctl(dst.fileno(), ficlone, src.fileno())
        shutil.copystat(source, destination, follow_symlinks=True)
        return True
    except OSError as exc:
        destination.unlink(missing_ok=True)
        if exc.errno in {
            errno.EXDEV,
            errno.ENOTSUP,
            getattr(errno, "EOPNOTSUPP", errno.ENOTSUP),
            errno.ENOSYS,
            errno.EINVAL,
        }:
            return False
        raise


def copy_storage_efficient(
    source: Path,
    destination: Path,
    *,
    require_clone: bool = False,
) -> str:
    """Copy a file, preferring filesystem copy-on-write clones.

    Returns "clone" when no full physical copy was allocated and "copy" for the
    portable fallback.
    """

    source = source.resolve()
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)

    if _clonefile_macos(source, destination):
        return "clone"
    if _reflink_linux(source, destination):
        return "clone"
    if require_clone:
        raise RuntimeError(
            "copy-on-write clone is unavailable on this filesystem; "
            "refusing a full physical copy because storage-safe mode is required"
        )
    shutil.copy2(source, destination)
    return "copy"


def remove_materialized_world(archive: Path) -> int:
    """Remove one mutable per-case world and every revision sidecar beside it."""

    archive = archive.resolve()
    removed = 0
    paths = [archive]
    if archive.parent.exists():
        paths.extend(sorted(archive.parent.glob(archive.name + ".*")))
    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        try:
            if path.is_file() or path.is_symlink():
                path.unlink()
                removed += 1
        except FileNotFoundError:
            pass
    return removed


def allocated_bytes(path: Path) -> int:
    """Return physical allocated bytes where st_blocks is available."""

    if not path.exists():
        return 0
    if path.is_file():
        stat = path.stat()
        return int(getattr(stat, "st_blocks", 0) * 512 or stat.st_size)
    total = 0
    for entry in path.rglob("*"):
        try:
            if entry.is_file():
                stat = entry.stat()
                total += int(getattr(stat, "st_blocks", 0) * 512 or stat.st_size)
        except FileNotFoundError:
            continue
    return total


def logical_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for entry in path.rglob("*"):
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except FileNotFoundError:
            continue
    return total


def free_bytes(path: Path) -> int:
    usage = shutil.disk_usage(path.resolve())
    return int(usage.free)
