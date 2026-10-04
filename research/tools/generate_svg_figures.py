#!/usr/bin/env python3
"""Generate deterministic vector research figures from aggregate MAVEB CSV results.

The generator intentionally uses only the Python standard library so CI can regenerate figures
without a plotting stack. It writes plain SVG; publication styling can later be applied by replacing
this backend while retaining the same raw-data contract.
"""

from __future__ import annotations

import argparse
import csv
import html
import math
from pathlib import Path
from typing import Iterable


def number(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def extent(values: Iterable[float]) -> tuple[float, float]:
    values = list(values)
    if not values:
        raise ValueError("figure has no numeric data")
    low, high = min(values), max(values)
    if low == high:
        pad = max(abs(low) * 0.05, 1.0)
        return low - pad, high + pad
    pad = (high - low) * 0.06
    return low - pad, high + pad


def scatter_svg(
    rows: list[dict[str, str]],
    x_key: str,
    y_key: str,
    x_label: str,
    y_label: str,
    title: str,
) -> str:
    points = []
    for row in rows:
        x = number(row.get(x_key))
        y = number(row.get(y_key))
        if x is None or y is None:
            continue
        points.append((x, y, row.get("experiment_id", "")))
    if not points:
        raise ValueError(f"no rows contain both {x_key} and {y_key}")

    width, height = 900, 560
    left, right, top, bottom = 90, 30, 60, 75
    plot_width = width - left - right
    plot_height = height - top - bottom
    xmin, xmax = extent(p[0] for p in points)
    ymin, ymax = extent(p[1] for p in points)

    def sx(value: float) -> float:
        return left + (value - xmin) / (xmax - xmin) * plot_width

    def sy(value: float) -> float:
        return top + (ymax - value) / (ymax - ymin) * plot_height

    parts = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}'>",
        "<rect width='100%' height='100%' fill='white'/>",
        f"<text x='{width/2}' y='30' text-anchor='middle' font-family='sans-serif' font-size='18'>{html.escape(title)}</text>",
        f"<line x1='{left}' y1='{top}' x2='{left}' y2='{top+plot_height}' stroke='black'/>",
        f"<line x1='{left}' y1='{top+plot_height}' x2='{left+plot_width}' y2='{top+plot_height}' stroke='black'/>",
    ]
    for tick in range(6):
        fraction = tick / 5
        xv = xmin + fraction * (xmax - xmin)
        x = sx(xv)
        parts.append(f"<line x1='{x:.2f}' y1='{top+plot_height}' x2='{x:.2f}' y2='{top+plot_height+5}' stroke='black'/>")
        parts.append(f"<text x='{x:.2f}' y='{top+plot_height+22}' text-anchor='middle' font-family='sans-serif' font-size='11'>{xv:.3g}</text>")
        yv = ymin + fraction * (ymax - ymin)
        y = sy(yv)
        parts.append(f"<line x1='{left-5}' y1='{y:.2f}' x2='{left}' y2='{y:.2f}' stroke='black'/>")
        parts.append(f"<text x='{left-9}' y='{y+4:.2f}' text-anchor='end' font-family='sans-serif' font-size='11'>{yv:.3g}</text>")
    for x_value, y_value, identifier in points:
        parts.append(
            f"<circle cx='{sx(x_value):.2f}' cy='{sy(y_value):.2f}' r='4' fill='none' stroke='black'>"
            f"<title>{html.escape(identifier)}</title></circle>"
        )
    parts.extend(
        [
            f"<text x='{left+plot_width/2}' y='{height-20}' text-anchor='middle' font-family='sans-serif' font-size='14'>{html.escape(x_label)}</text>",
            f"<text x='20' y='{top+plot_height/2}' transform='rotate(-90 20 {top+plot_height/2})' text-anchor='middle' font-family='sans-serif' font-size='14'>{html.escape(y_label)}</text>",
            "</svg>",
        ]
    )
    return "".join(parts)


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    rows = read_rows(args.runs_csv)
    write_atomic(
        args.output_dir / "quality-vs-gpu-p95.svg",
        scatter_svg(rows, "gpu_p95_ms", "psnr", "GPU p95 (ms)", "PSNR (dB)", "Quality vs GPU latency"),
    )
    ulr_keys = sorted({key for row in rows for key in row if key.startswith("ulr_")})
    for key in ulr_keys:
        if any(number(row.get("changed_fraction")) is not None and number(row.get(key)) is not None for row in rows):
            write_atomic(
                args.output_dir / f"changed-fraction-vs-{key}.svg",
                scatter_svg(
                    rows,
                    "changed_fraction",
                    key,
                    "Changed world fraction",
                    key.removeprefix("ulr_") + " ULR",
                    "Update locality scaling",
                ),
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
