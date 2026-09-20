#!/usr/bin/env python3
"""Synthetic opportunity probe for regional temporal-history invalidation.

Projects conservative dirty world-space AABBs into a pinhole camera and measures
how much of the screen a coarse invalidation mask would cover. This answers only
whether local history invalidation has enough potential sparsity to justify a
real renderer prototype.
"""
import json
import math
import numpy as np

WIDTH, HEIGHT = 1920, 1080
GRID_WIDTH, GRID_HEIGHT = 240, 135
FOV_Y = math.radians(60.0)
FY = 0.5 * HEIGHT / math.tan(FOV_Y / 2.0)
FX = FY
CX, CY = WIDTH / 2.0, HEIGHT / 2.0


def project(point):
    x, y, z = point
    if z <= 0.05:
        return None
    return np.array([FX * x / z + CX, FY * (-y) / z + CY])


def rectangle_for_box(center, size):
    half = size / 2.0
    projected = []
    for dx in (-half[0], half[0]):
        for dy in (-half[1], half[1]):
            for dz in (-half[2], half[2]):
                point = project(center + np.array([dx, dy, dz]))
                if point is not None:
                    projected.append(point)
    if not projected:
        return None
    points = np.asarray(projected)
    low = np.maximum(points.min(axis=0), [0.0, 0.0])
    high = np.minimum(points.max(axis=0), [WIDTH - 1.0, HEIGHT - 1.0])
    if np.any(high <= low):
        return None
    return (*low, *high)


def run():
    rng = np.random.default_rng(12)
    summary = {}
    for box_count in (1, 2, 4, 8, 16, 32, 64, 128):
        fractions = []
        for _ in range(500):
            mask = np.zeros((GRID_HEIGHT, GRID_WIDTH), dtype=bool)
            for _ in range(box_count):
                z = rng.uniform(2.0, 10.0)
                x_max = z * math.tan(FOV_Y / 2.0) * (WIDTH / HEIGHT)
                y_max = z * math.tan(FOV_Y / 2.0)
                center = np.array([
                    rng.uniform(-0.75 * x_max, 0.75 * x_max),
                    rng.uniform(-0.75 * y_max, 0.75 * y_max),
                    z,
                ])
                size = rng.uniform(0.08, 0.7, 3)
                rectangle = rectangle_for_box(center, size)
                if rectangle is None:
                    continue

                x0, y0, x1, y1 = rectangle
                # Conservative 8-pixel screen-space halo.
                x0, y0 = max(0.0, x0 - 8.0), max(0.0, y0 - 8.0)
                x1, y1 = min(WIDTH - 1.0, x1 + 8.0), min(HEIGHT - 1.0, y1 + 8.0)

                gx0 = max(0, int(math.floor(x0 / WIDTH * GRID_WIDTH)))
                gx1 = min(GRID_WIDTH, int(math.ceil((x1 + 1.0) / WIDTH * GRID_WIDTH)))
                gy0 = max(0, int(math.floor(y0 / HEIGHT * GRID_HEIGHT)))
                gy1 = min(GRID_HEIGHT, int(math.ceil((y1 + 1.0) / HEIGHT * GRID_HEIGHT)))
                mask[gy0:gy1, gx0:gx1] = True
            fractions.append(float(mask.mean()))

        values = np.asarray(fractions)
        summary[str(box_count)] = {
            "median": float(np.median(values)),
            "p95": float(np.quantile(values, 0.95)),
            "mean": float(values.mean()),
        }

    return {
        "schemaVersion": 1,
        "experiment": "temporal-local-invalidation-opportunity-v0",
        "configuration": {
            "trialsPerBoxCount": 500,
            "dirtyBoxCounts": [1, 2, 4, 8, 16, 32, 64, 128],
            "frame": [WIDTH, HEIGHT],
            "coarseMask": [GRID_WIDTH, GRID_HEIGHT],
            "verticalFovDegrees": 60.0,
            "depthRangeMeters": [2.0, 10.0],
            "boxExtentRangeMeters": [0.08, 0.7],
            "screenHaloPixels": 8,
        },
        "summary": summary,
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
