#!/usr/bin/env python3
"""Cheap falsification probe for dependency-coherent stable texture page assignment.

A stable page scheme preserves addresses, but a previous probe showed that randomly scattered slot
membership can turn a 1% world change into nearly global page invalidation. This probe asks whether
a simple spatially coherent allocator (Morton order over persistent RegionKeys) materially changes
that result for spatially local 3D edits.

This is a combinatorial dependency probe, not a texture-quality or GPU-performance benchmark.
"""

from __future__ import annotations

import json
import math
import platform
import sys

import numpy as np

GRID = 64
ACTIVE_SLOTS = GRID ** 3
PAGE_SIZES = (64, 256, 1024, 4096)
CUBE_SIDES = (6, 14, 24)  # ~0.08%, ~1.05%, ~5.27% of a 64^3 world
SEEDS = tuple(range(20))
RANDOM_ALLOCATION_SEED = 20260920


def part1by2(value: np.ndarray) -> np.ndarray:
    """Expand 6-bit coordinates so x/y/z bits can be interleaved into a Morton key."""
    x = value.astype(np.uint64, copy=True)
    x = (x | (x << np.uint64(16))) & np.uint64(0x030000FF)
    x = (x | (x << np.uint64(8))) & np.uint64(0x0300F00F)
    x = (x | (x << np.uint64(4))) & np.uint64(0x030C30C3)
    x = (x | (x << np.uint64(2))) & np.uint64(0x09249249)
    return x


def morton_keys(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
    return part1by2(x) | (part1by2(y) << np.uint64(1)) | (
        part1by2(z) << np.uint64(2)
    )


def build_slot_maps() -> tuple[np.ndarray, np.ndarray]:
    coordinates = np.indices((GRID, GRID, GRID), dtype=np.uint64)
    x = coordinates[0].ravel()
    y = coordinates[1].ravel()
    z = coordinates[2].ravel()

    morton = morton_keys(x, y, z)
    morton_order = np.argsort(morton, kind="stable")
    morton_slot = np.empty(ACTIVE_SLOTS, dtype=np.uint32)
    morton_slot[morton_order] = np.arange(ACTIVE_SLOTS, dtype=np.uint32)

    rng = np.random.default_rng(RANDOM_ALLOCATION_SEED)
    random_order = rng.permutation(ACTIVE_SLOTS)
    random_slot = np.empty(ACTIVE_SLOTS, dtype=np.uint32)
    random_slot[random_order] = np.arange(ACTIVE_SLOTS, dtype=np.uint32)
    return morton_slot, random_slot


def flat_ids_for_cube(start_x: int, start_y: int, start_z: int, side: int) -> np.ndarray:
    xs = np.arange(start_x, start_x + side, dtype=np.int64)
    ys = np.arange(start_y, start_y + side, dtype=np.int64)
    zs = np.arange(start_z, start_z + side, dtype=np.int64)
    x, y, z = np.meshgrid(xs, ys, zs, indexing="ij")
    return ((x * GRID + y) * GRID + z).ravel().astype(np.uint32)


def dirty_page_fraction(
    slots: np.ndarray, changed_ids: np.ndarray, slots_per_page: int
) -> float:
    page_count = math.ceil(ACTIVE_SLOTS / slots_per_page)
    pages = np.unique(slots[changed_ids] // slots_per_page)
    return float(pages.size / page_count)


def fragmentation_ratio(
    slots: np.ndarray, changed_ids: np.ndarray, slots_per_page: int
) -> float:
    """Dirty page capacity / truly changed slot count; 1 is the ideal whole-page lower bound."""
    dirty_pages = np.unique(slots[changed_ids] // slots_per_page).size
    return float((dirty_pages * slots_per_page) / changed_ids.size)


def main() -> int:
    morton_slot, random_slot = build_slot_maps()
    rows = []

    for side in CUBE_SIDES:
        changed_count = side ** 3
        actual_fraction = changed_count / ACTIVE_SLOTS

        for slots_per_page in PAGE_SIZES:
            morton_dirty = []
            random_dirty = []
            morton_fragmentation = []
            random_fragmentation = []

            for seed in SEEDS:
                rng = np.random.default_rng(seed)
                max_start = GRID - side
                sx, sy, sz = (
                    int(rng.integers(0, max_start + 1)),
                    int(rng.integers(0, max_start + 1)),
                    int(rng.integers(0, max_start + 1)),
                )
                changed = flat_ids_for_cube(sx, sy, sz, side)

                morton_dirty.append(
                    dirty_page_fraction(morton_slot, changed, slots_per_page)
                )
                random_dirty.append(
                    dirty_page_fraction(random_slot, changed, slots_per_page)
                )
                morton_fragmentation.append(
                    fragmentation_ratio(morton_slot, changed, slots_per_page)
                )
                random_fragmentation.append(
                    fragmentation_ratio(random_slot, changed, slots_per_page)
                )

            page_count = math.ceil(ACTIVE_SLOTS / slots_per_page)
            ideal_min_pages = math.ceil(changed_count / slots_per_page)
            ideal_page_fraction = ideal_min_pages / page_count

            rows.append(
                {
                    "cubeSide": side,
                    "changedSlots": changed_count,
                    "actualChangedFraction": actual_fraction,
                    "slotsPerPage": slots_per_page,
                    "allocatedPages": page_count,
                    "idealWholePageFraction": ideal_page_fraction,
                    "mortonDirtyPageFractionMean": float(np.mean(morton_dirty)),
                    "mortonDirtyPageFractionP95": float(
                        np.percentile(np.asarray(morton_dirty), 95)
                    ),
                    "randomDirtyPageFractionMean": float(np.mean(random_dirty)),
                    "randomDirtyPageFractionP95": float(
                        np.percentile(np.asarray(random_dirty), 95)
                    ),
                    "mortonCapacityAmplificationMean": float(
                        np.mean(morton_fragmentation)
                    ),
                    "randomCapacityAmplificationMean": float(
                        np.mean(random_fragmentation)
                    ),
                    "unchangedAddressSurvival": 1.0,
                }
            )

    output = {
        "schemaVersion": 1,
        "experiment": "spatial-page-allocation-v3",
        "status": "synthetic-dependency-allocation-probe",
        "warning": (
            "Not a texture-quality, renderer, allocator-fragmentation-over-time, or GPU timing "
            "benchmark. It isolates how stable slot assignment affects whole-page dirty scope for "
            "axis-aligned local 3D edits."
        ),
        "configuration": {
            "grid": [GRID, GRID, GRID],
            "activeSlots": ACTIVE_SLOTS,
            "pageSizes": list(PAGE_SIZES),
            "cubeSides": list(CUBE_SIDES),
            "seeds": list(SEEDS),
            "randomAllocationSeed": RANDOM_ALLOCATION_SEED,
        },
        "runtime": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "rows": rows,
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
