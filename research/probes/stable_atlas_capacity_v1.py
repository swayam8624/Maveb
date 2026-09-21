#!/usr/bin/env python3
"""Analytical stress probe for fixed-capacity stable texture-atlas addressing.

This does not estimate rendered quality. It computes the deterministic grid/tile
resolution implied by the current StableTextureAtlasLayout proposal as slot
capacity grows, and compares active-count overprovisioning penalties.
"""
from __future__ import annotations

import json
import math

ATLAS_SIZE = 8192
GUTTER = 4
CAPACITIES = [
    1_000,
    2_500,
    5_000,
    10_000,
    25_000,
    50_000,
    100_000,
    150_000,
    200_000,
    250_000,
    400_000,
    500_000,
    750_000,
    1_000_000,
]
OVERPROVISION_CASES = [
    (10_000, 10_000),
    (10_000, 25_000),
    (10_000, 100_000),
    (50_000, 100_000),
    (100_000, 250_000),
]


def layout(capacity: int) -> dict[str, int | float | bool]:
    columns = math.ceil(math.sqrt(capacity))
    rows = math.ceil(capacity / columns)
    cell = min(ATLAS_SIZE // columns, ATLAS_SIZE // rows)
    inner = cell - 2 * GUTTER
    # Current implementation requires cell > 2*gutter + 1.
    valid = cell > 2 * GUTTER + 1
    return {
        "capacity": capacity,
        "columns": columns,
        "rows": rows,
        "cellPixels": cell,
        "innerPixels": max(0, inner),
        "approxTriangleTexels": max(0.0, inner * inner / 2.0),
        "validByCurrentContract": valid,
    }


def run() -> dict:
    by_capacity = [layout(capacity) for capacity in CAPACITIES]
    penalties = []
    for active, capacity in OVERPROVISION_CASES:
        active_layout = layout(active)
        reserved_layout = layout(capacity)
        active_inner = int(active_layout["innerPixels"])
        reserved_inner = int(reserved_layout["innerPixels"])
        texel_ratio = (
            (reserved_inner * reserved_inner) / (active_inner * active_inner)
            if active_inner > 0
            else 0.0
        )
        penalties.append(
            {
                "activeTriangles": active,
                "reservedCapacity": capacity,
                "activeCountInnerPixels": active_inner,
                "stableCapacityInnerPixels": reserved_inner,
                "perTriangleTexelAreaRatioVsActiveCountLayout": texel_ratio,
            }
        )

    return {
        "schemaVersion": 1,
        "experiment": "stable-atlas-capacity-v1",
        "status": "deterministic-analytical-probe",
        "warning": (
            "This computes atlas-addressing capacity and nominal texel budget only; "
            "it is not a rendered-quality benchmark."
        ),
        "atlasSize": ATLAS_SIZE,
        "gutterPixels": GUTTER,
        "capacitySweep": by_capacity,
        "overprovisioning": penalties,
        "decision": (
            "FIXED GLOBAL STABLE ATLAS SURVIVES ONLY AS SMALL/MEDIUM-SCENE INFRASTRUCTURE. "
            "For large persistent worlds, stable addressing needs paging/sparse residency/another "
            "indirection so capacity growth does not collapse texel resolution globally."
        ),
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
