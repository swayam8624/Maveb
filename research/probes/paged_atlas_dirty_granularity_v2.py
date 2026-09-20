#!/usr/bin/env python3
"""Synthetic kill probe for paged stable texture addressing.

The probe asks whether stable texture pages are sufficient for update locality. It does not model
rendering quality. For a fixed active slot population, it compares randomly scattered patch changes
against one spatially clustered contiguous change. It reports the fraction of allocated pages that
would need rewriting if upload/invalidation granularity were a whole page.

A good stable-address scheme must preserve addresses *and* keep dependency/write granularity local.
"""

from __future__ import annotations

import json
import math
import platform
import sys

import numpy as np

ACTIVE_SLOTS = 250_000
SLOTS_PER_PAGE = (64, 256, 1024, 4096)
CHANGE_FRACTIONS = (0.001, 0.01, 0.05)
SEEDS = tuple(range(10))


def page_count(active_slots: int, slots_per_page: int) -> int:
    return math.ceil(active_slots / slots_per_page)


def random_dirty_fraction(
    active_slots: int, slots_per_page: int, changed_slots: int, seed: int
) -> float:
    rng = np.random.default_rng(seed)
    changed = rng.choice(active_slots, size=changed_slots, replace=False)
    dirty_pages = np.unique(changed // slots_per_page).size
    return float(dirty_pages / page_count(active_slots, slots_per_page))


def clustered_dirty_fraction(
    active_slots: int, slots_per_page: int, changed_slots: int
) -> float:
    # One contiguous slot interval approximates a spatially coherent allocator where nearby patches
    # share nearby stable page slots. Offset avoids giving the cluster a page-aligned advantage.
    start = min(active_slots - changed_slots, slots_per_page // 3)
    first_page = start // slots_per_page
    last_page = (start + changed_slots - 1) // slots_per_page
    dirty_pages = last_page - first_page + 1
    return float(dirty_pages / page_count(active_slots, slots_per_page))


def main() -> int:
    rows = []
    for slots_per_page in SLOTS_PER_PAGE:
        pages = page_count(ACTIVE_SLOTS, slots_per_page)
        for change_fraction in CHANGE_FRACTIONS:
            changed_slots = max(1, int(round(ACTIVE_SLOTS * change_fraction)))
            random_values = [
                random_dirty_fraction(
                    ACTIVE_SLOTS, slots_per_page, changed_slots, seed
                )
                for seed in SEEDS
            ]
            clustered = clustered_dirty_fraction(
                ACTIVE_SLOTS, slots_per_page, changed_slots
            )
            rows.append(
                {
                    "slotsPerPage": slots_per_page,
                    "allocatedPages": pages,
                    "changeFraction": change_fraction,
                    "changedSlots": changed_slots,
                    "randomDirtyPageFractionMean": float(np.mean(random_values)),
                    "randomDirtyPageFractionMin": float(np.min(random_values)),
                    "randomDirtyPageFractionMax": float(np.max(random_values)),
                    "clusteredDirtyPageFraction": clustered,
                    "idealSubPageWriteFraction": change_fraction,
                    "addressSurvivalForUnchangedSlots": 1.0,
                }
            )

    output = {
        "schemaVersion": 1,
        "experiment": "paged-atlas-dirty-granularity-v2",
        "status": "synthetic-dependency-granularity-probe",
        "warning": (
            "Not a texture-quality or GPU timing benchmark. Page rewrite fraction assumes whole-page "
            "upload/invalidation granularity; sub-page writes are reported as an ideal lower bound."
        ),
        "configuration": {
            "activeSlots": ACTIVE_SLOTS,
            "slotsPerPage": list(SLOTS_PER_PAGE),
            "changeFractions": list(CHANGE_FRACTIONS),
            "seeds": list(SEEDS),
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
