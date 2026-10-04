#!/usr/bin/env python3
"""Cheap structural probe for a compact Gaussian region-index base+delta overlay.

This is intentionally a NumPy reference experiment, not production C++ and not an Apple-silicon
benchmark. It tests one narrow hypothesis: after a small fraction of primitives change spatial
regions, can an immutable sorted base plus a sorted delta preserve exact dirty-region selection
while avoiding a full million-entry resort?

The probe reports raw maintenance/query time and explicit array storage. Timings are useful only
within this implementation/runtime.
"""

from __future__ import annotations

import json
import platform
import sys
import time
from dataclasses import asdict, dataclass

import numpy as np

GAUSSIANS = 1_000_000
EXTENT = 512
DIRTY_OCCUPIED_FRACTION = 0.001
QUERY_REPEATS = 3
SEED = 42
FRACTIONS = (0.01, 0.02, 0.05, 0.10, 0.20, 0.40)


@dataclass
class Level:
    changed_fraction: float
    changed_gaussians: int
    dirty_regions: int
    selected_gaussians: int
    full_rebuild_ms: float
    delta_rebuild_ms: float
    oracle_query_median_ms: float
    overlay_query_median_ms: float
    oracle_storage_bytes: int
    overlay_storage_bytes: int
    exact_selection_agreement: bool


def packed_keys(rng: np.random.Generator, count: int) -> np.ndarray:
    xyz = rng.integers(0, EXTENT, size=(count, 3), dtype=np.uint64)
    return xyz[:, 0] + np.uint64(EXTENT) * (
        xyz[:, 1] + np.uint64(EXTENT) * xyz[:, 2]
    )


def sorted_index(keys: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    indices = np.arange(keys.size, dtype=np.uint32)
    order = np.lexsort((indices, keys))
    return keys[order], indices[order]


def choose_dirty(sorted_keys: np.ndarray) -> np.ndarray:
    occupied = np.unique(sorted_keys)
    wanted = max(1, int(np.ceil(occupied.size * DIRTY_OCCUPIED_FRACTION)))
    positions = (np.arange(wanted, dtype=np.uint64) * occupied.size) // wanted
    positions = np.minimum(positions, occupied.size - 1).astype(np.int64)
    return np.unique(occupied[positions])


def query_flat(
    sorted_keys: np.ndarray, sorted_indices: np.ndarray, dirty: np.ndarray
) -> np.ndarray:
    pieces: list[np.ndarray] = []
    for key in dirty:
        first = np.searchsorted(sorted_keys, key, side="left")
        last = np.searchsorted(sorted_keys, key, side="right")
        if last > first:
            pieces.append(sorted_indices[first:last])
    if not pieces:
        return np.empty(0, dtype=np.uint32)
    return np.sort(np.concatenate(pieces))


def query_overlay(
    base_keys: np.ndarray,
    base_indices: np.ndarray,
    delta_keys: np.ndarray,
    delta_indices: np.ndarray,
    moved: np.ndarray,
    dirty: np.ndarray,
) -> np.ndarray:
    pieces: list[np.ndarray] = []
    for key in dirty:
        first = np.searchsorted(base_keys, key, side="left")
        last = np.searchsorted(base_keys, key, side="right")
        if last > first:
            candidates = base_indices[first:last]
            stable = candidates[~moved[candidates]]
            if stable.size:
                pieces.append(stable)

        first = np.searchsorted(delta_keys, key, side="left")
        last = np.searchsorted(delta_keys, key, side="right")
        if last > first:
            pieces.append(delta_indices[first:last])

    if not pieces:
        return np.empty(0, dtype=np.uint32)
    return np.sort(np.concatenate(pieces))


def timed_ms(callable_) -> tuple[float, object]:
    start = time.perf_counter()
    value = callable_()
    return (time.perf_counter() - start) * 1000.0, value


def median_query_ms(callable_) -> float:
    values = []
    checksum = 0
    for _ in range(QUERY_REPEATS):
        elapsed, selected = timed_ms(callable_)
        checksum += int(selected.size)
        values.append(elapsed)
    if checksum == 0:
        raise RuntimeError("zero query checksum")
    return float(np.median(np.asarray(values, dtype=np.float64)))


def main() -> int:
    rng = np.random.default_rng(SEED)
    base_unsorted = packed_keys(rng, GAUSSIANS)
    base_build_ms, base_pair = timed_ms(lambda: sorted_index(base_unsorted))
    base_keys, base_indices = base_pair

    permutation = rng.permutation(GAUSSIANS).astype(np.uint32, copy=False)
    target_keys = packed_keys(rng, GAUSSIANS)

    levels: list[Level] = []
    for fraction in FRACTIONS:
        changed_count = int(GAUSSIANS * fraction)
        changed = permutation[:changed_count]

        current = base_unsorted.copy()
        current[changed] = target_keys[changed]

        full_rebuild_ms, oracle_pair = timed_ms(lambda: sorted_index(current))
        oracle_keys, oracle_indices = oracle_pair

        delta_build_ms, delta_pair = timed_ms(
            lambda: sorted_index(current[changed])
        )
        delta_keys, delta_local_indices = delta_pair
        delta_indices = changed[delta_local_indices]

        moved = np.zeros(GAUSSIANS, dtype=np.bool_)
        moved[changed] = True
        dirty = choose_dirty(oracle_keys)

        oracle = query_flat(oracle_keys, oracle_indices, dirty)
        overlay = query_overlay(
            base_keys,
            base_indices,
            delta_keys,
            delta_indices,
            moved,
            dirty,
        )
        exact = bool(np.array_equal(oracle, overlay))
        if not exact:
            raise RuntimeError(
                f"base+delta selection mismatch at changed fraction {fraction}"
            )

        oracle_query = median_query_ms(
            lambda: query_flat(oracle_keys, oracle_indices, dirty)
        )
        overlay_query = median_query_ms(
            lambda: query_overlay(
                base_keys,
                base_indices,
                delta_keys,
                delta_indices,
                moved,
                dirty,
            )
        )

        oracle_storage = int(oracle_keys.nbytes + oracle_indices.nbytes)
        overlay_storage = int(
            base_keys.nbytes
            + base_indices.nbytes
            + delta_keys.nbytes
            + delta_indices.nbytes
            + moved.nbytes
        )
        levels.append(
            Level(
                changed_fraction=fraction,
                changed_gaussians=changed_count,
                dirty_regions=int(dirty.size),
                selected_gaussians=int(oracle.size),
                full_rebuild_ms=full_rebuild_ms,
                delta_rebuild_ms=delta_build_ms,
                oracle_query_median_ms=oracle_query,
                overlay_query_median_ms=overlay_query,
                oracle_storage_bytes=oracle_storage,
                overlay_storage_bytes=overlay_storage,
                exact_selection_agreement=exact,
            )
        )

    output = {
        "schemaVersion": 1,
        "experiment": "gaussian-index-overlay-numpy-v3",
        "status": "synthetic-numpy-reference-probe",
        "warning": (
            "Not production C++, not Metal, and not an Apple-silicon benchmark. "
            "Use timings only as within-runtime structural evidence."
        ),
        "configuration": {
            "gaussians": GAUSSIANS,
            "cellCoordinateExtent": EXTENT,
            "dirtyOccupiedCellFraction": DIRTY_OCCUPIED_FRACTION,
            "queryRepeats": QUERY_REPEATS,
            "seed": SEED,
        },
        "runtime": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "baseBuildMs": base_build_ms,
        "baseStorageBytes": int(base_keys.nbytes + base_indices.nbytes),
        "levels": [asdict(level) for level in levels],
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
