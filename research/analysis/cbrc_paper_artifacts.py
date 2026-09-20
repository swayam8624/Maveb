#!/usr/bin/env python3
"""Deterministic CBRC paper-analysis artifacts from machine-readable evidence.

No plotting dependency is required. The script emits CSV source tables plus
simple SVG figures so every plotted point remains inspectable and diffable.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]
    if not rows:
        raise ValueError("analysis requires at least one evidence row")
    return rows


def finite(value: Any, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires values")
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    t = pos - lo
    return ordered[lo] * (1 - t) + ordered[hi] * t


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def esc(text: Any) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def svg_frame(title: str, body: str, width: int = 900, height: int = 560) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        '<rect width="100%" height="100%" fill="white"/>'
        f'<text x="30" y="34" font-family="sans-serif" font-size="20">{esc(title)}</text>'
        f'{body}</svg>\n'
    )


def scatter_svg(
    title: str,
    points: list[tuple[float, float, str]],
    *,
    x_label: str,
    y_label: str,
    diagonal: bool = False,
) -> str:
    width, height = 900, 560
    left, top, right, bottom = 80, 60, 30, 70
    plot_w = width - left - right
    plot_h = height - top - bottom
    xs = [p[0] for p in points] or [0.0]
    ys = [p[1] for p in points] or [0.0]
    maximum = max(max(xs), max(ys), 1e-12) if diagonal else None
    xmin, xmax = (0.0, maximum) if diagonal else (min(xs), max(xs))
    ymin, ymax = (0.0, maximum) if diagonal else (min(ys), max(ys))
    if xmax <= xmin:
        xmax = xmin + 1.0
    if ymax <= ymin:
        ymax = ymin + 1.0

    def sx(x: float) -> float:
        return left + (x - xmin) / (xmax - xmin) * plot_w

    def sy(y: float) -> float:
        return top + plot_h - (y - ymin) / (ymax - ymin) * plot_h

    pieces = [
        f'<line x1="{left}" y1="{top+plot_h}" x2="{left+plot_w}" y2="{top+plot_h}" stroke="black"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top+plot_h}" stroke="black"/>',
    ]
    if diagonal:
        pieces.append(
            f'<line x1="{sx(0)}" y1="{sy(0)}" x2="{sx(maximum)}" y2="{sy(maximum)}" '
            'stroke="gray" stroke-dasharray="6,5"/>'
        )
    for x, y, label in points:
        pieces.append(
            f'<circle cx="{sx(x):.3f}" cy="{sy(y):.3f}" r="4">'
            f'<title>{esc(label)}: x={x:.6g}, y={y:.6g}</title></circle>'
        )
    pieces.extend(
        [
            f'<text x="{left+plot_w/2}" y="{height-20}" text-anchor="middle" '
            f'font-family="sans-serif" font-size="14">{esc(x_label)}</text>',
            f'<text transform="translate(20 {top+plot_h/2}) rotate(-90)" '
            f'text-anchor="middle" font-family="sans-serif" font-size="14">{esc(y_label)}</text>',
            f'<text x="{left}" y="{top+plot_h+24}" font-family="monospace" font-size="11">{xmin:.3g}</text>',
            f'<text x="{left+plot_w-35}" y="{top+plot_h+24}" font-family="monospace" font-size="11">{xmax:.3g}</text>',
            f'<text x="{left-55}" y="{top+plot_h}" font-family="monospace" font-size="11">{ymin:.3g}</text>',
            f'<text x="{left-55}" y="{top+10}" font-family="monospace" font-size="11">{ymax:.3g}</text>',
        ]
    )
    return svg_frame(title, "".join(pieces), width, height)


def bar_svg(title: str, entries: list[tuple[str, float]], y_label: str) -> str:
    width, height = 900, 560
    left, top, right, bottom = 80, 60, 30, 100
    plot_w = width - left - right
    plot_h = height - top - bottom
    ymax = max([v for _, v in entries] + [1e-12])
    bar_w = plot_w / max(len(entries), 1) * 0.7
    gap = plot_w / max(len(entries), 1)
    pieces = [
        f'<line x1="{left}" y1="{top+plot_h}" x2="{left+plot_w}" y2="{top+plot_h}" stroke="black"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top+plot_h}" stroke="black"/>',
    ]
    for i, (name, value) in enumerate(entries):
        x = left + i * gap + (gap - bar_w) / 2
        h = value / ymax * plot_h
        y = top + plot_h - h
        pieces.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_w:.2f}" height="{h:.2f}">'
            f'<title>{esc(name)}: {value:.6g}</title></rect>'
        )
        pieces.append(
            f'<text x="{x+bar_w/2:.2f}" y="{top+plot_h+18}" text-anchor="end" '
            f'transform="rotate(-35 {x+bar_w/2:.2f} {top+plot_h+18})" '
            f'font-family="sans-serif" font-size="10">{esc(name)}</text>'
        )
    pieces.append(
        f'<text transform="translate(20 {top+plot_h/2}) rotate(-90)" text-anchor="middle" '
        f'font-family="sans-serif" font-size="14">{esc(y_label)}</text>'
    )
    return svg_frame(title, "".join(pieces), width, height)


def f1(rows: list[dict[str, Any]], output: Path) -> None:
    table = []
    points = []
    for row in rows:
        for name, qoi in row["qois"].items():
            actual = finite(qoi["measured_full_reference_error"], "actual")
            bound = finite(qoi["certified_bound"], "bound")
            item = {
                "scene": row.get("scene_id", ""),
                "revision": row.get("revision_id", ""),
                "qoi": name,
                "actual": actual,
                "bound": bound,
                "epsilon": finite(qoi["epsilon"], "epsilon"),
            }
            table.append(item)
            points.append((actual, bound, f'{item["scene"]}/{item["revision"]}/{name}'))
    write_csv(output / "F1_actual_vs_bound.csv", list(table[0]), table)
    (output / "F1_actual_vs_bound.svg").write_text(
        scatter_svg(
            "F1 — measured error vs certified bound",
            points,
            x_label="measured full-reference error",
            y_label="certified bound",
            diagonal=True,
        )
    )


def f2(rows: list[dict[str, Any]], output: Path) -> None:
    table = []
    points = []
    for row in rows:
        full = finite(row["full_work"], "full_work")
        work = finite(row["planner_work"], "planner_work")
        ratio = work / full if full > 0 else 0.0
        changed = finite(row.get("changed_fraction", 0.0), "changed_fraction")
        coupling = str(row.get("coupling_regime", "unknown"))
        table.append(
            {
                "scene": row.get("scene_id", ""),
                "revision": row.get("revision_id", ""),
                "coupling": coupling,
                "changed_fraction": changed,
                "work_ratio_full": ratio,
            }
        )
        points.append((changed, ratio, coupling))
    write_csv(output / "F2_work_vs_changed_fraction.csv", list(table[0]), table)
    (output / "F2_work_vs_changed_fraction.svg").write_text(
        scatter_svg(
            "F2 — work ratio vs changed fraction",
            points,
            x_label="changed fraction",
            y_label="planner work / full work",
        )
    )


def f3(rows: list[dict[str, Any]], output: Path) -> None:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        total = int(row.get("total_nodes", 0))
        cone = int(row.get("repair_cone_nodes", 0))
        if total > 0:
            grouped[str(row.get("coupling_regime", "unknown"))].append(cone / total)
    entries = [
        (name, statistics.median(values))
        for name, values in sorted(grouped.items())
        if values
    ]
    table = [{"coupling": name, "median_cone_fraction": value} for name, value in entries]
    if table:
        write_csv(output / "F3_coupling_cone.csv", list(table[0]), table)
    (output / "F3_coupling_cone.svg").write_text(
        bar_svg("F3 — coupling regime vs repair-cone fraction", entries, "median cone fraction")
    )


def f4(rows: list[dict[str, Any]], output: Path) -> None:
    buckets: dict[float, list[int]] = defaultdict(list)
    for row in rows:
        changed = round(float(row.get("changed_fraction", 0.0)), 6)
        buckets[changed].append(1 if row.get("fallback_full", False) else 0)
    table = [
        {
            "changed_fraction": changed,
            "fallback_rate": sum(values) / len(values),
            "count": len(values),
        }
        for changed, values in sorted(buckets.items())
    ]
    if table:
        write_csv(output / "F4_fallback_crossover.csv", list(table[0]), table)
    points = [
        (float(item["changed_fraction"]), float(item["fallback_rate"]), "fallback")
        for item in table
    ]
    (output / "F4_fallback_crossover.svg").write_text(
        scatter_svg(
            "F4 — automatic local-to-full crossover",
            points,
            x_label="changed fraction",
            y_label="fallback rate",
        )
    )


def f5(rows: list[dict[str, Any]], output: Path) -> None:
    values = []
    table = []
    for row in rows:
        for name, qoi in row["qois"].items():
            actual = float(qoi["measured_full_reference_error"])
            bound = float(qoi["certified_bound"])
            effectivity = bound / max(actual, 1e-15)
            values.append(effectivity)
            table.append(
                {
                    "scene": row.get("scene_id", ""),
                    "revision": row.get("revision_id", ""),
                    "qoi": name,
                    "effectivity": effectivity,
                }
            )
    write_csv(output / "F5_effectivity.csv", list(table[0]), table)
    sorted_values = sorted(values)
    points = [
        (i / max(len(sorted_values) - 1, 1), value, "effectivity")
        for i, value in enumerate(sorted_values)
    ]
    (output / "F5_effectivity.svg").write_text(
        scatter_svg(
            "F5 — certificate effectivity distribution",
            points,
            x_label="empirical quantile",
            y_label="bound / measured error",
        )
    )


def f6(rows: list[dict[str, Any]], output: Path) -> None:
    sums: dict[str, float] = defaultdict(float)
    fulls: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    units: dict[str, str] = {}
    for row in rows:
        ledger = row.get("work_ledger", {})
        domains = ledger.get("domains", ledger) if isinstance(ledger, dict) else {}
        for name, counter in domains.items():
            if not isinstance(counter, dict):
                continue
            sums[name] += float(counter.get("incremental", 0.0))
            fulls[name] += float(counter.get("full", 0.0))
            counts[name] += 1
            units[name] = str(counter.get("unit", ""))
    table = []
    entries = []
    for name in sorted(sums):
        ratio = sums[name] / fulls[name] if fulls[name] > 0 else 0.0
        table.append(
            {
                "domain": name,
                "incremental_sum": sums[name],
                "full_sum": fulls[name],
                "ratio": ratio,
                "unit": units[name],
                "records": counts[name],
            }
        )
        entries.append((name, ratio))
    if table:
        write_csv(output / "F6_layer_work.csv", list(table[0]), table)
    (output / "F6_layer_work.svg").write_text(
        bar_svg("F6 — per-layer work ledger", entries, "incremental / full")
    )


def f7(spatial: Path, output: Path, row: dict[str, Any]) -> None:
    with spatial.open(newline="") as stream:
        records = list(csv.DictReader(stream))
    if not records:
        raise ValueError("spatial evidence is empty")
    width = max(int(r["x"]) for r in records) + 1
    height = max(int(r["y"]) for r in records) + 1
    max_bound = max(float(r["certified_bound"]) for r in records) or 1.0
    max_actual = max(float(r["actual_rgb_linf"]) for r in records) or 1.0

    target_w = 760
    target_h = 420
    sx = target_w / width
    sy = target_h / height
    pieces = [
        '<text x="30" y="58" font-family="sans-serif" font-size="12">'
        'left half: certified support intensity · right half: actual residual intensity</text>'
    ]
    half = target_w / 2
    for record in records:
        x = int(record["x"])
        y = int(record["y"])
        bound = float(record["certified_bound"])
        actual = float(record["actual_rgb_linf"])
        if bound > 0:
            opacity = min(1.0, bound / max_bound)
            pieces.append(
                f'<rect x="{30 + x*sx/2:.2f}" y="{80+y*sy:.2f}" '
                f'width="{max(sx/2,0.2):.2f}" height="{max(sy,0.2):.2f}" '
                f'fill="black" fill-opacity="{opacity:.4f}"/>'
            )
        if actual > 0:
            opacity = min(1.0, actual / max_actual)
            pieces.append(
                f'<rect x="{30 + half + x*sx/2:.2f}" y="{80+y*sy:.2f}" '
                f'width="{max(sx/2,0.2):.2f}" height="{max(sy,0.2):.2f}" '
                f'fill="black" fill-opacity="{opacity:.4f}"/>'
            )
    cone_fraction = (
        int(row.get("repair_cone_nodes", 0)) / int(row.get("total_nodes", 1))
        if int(row.get("total_nodes", 0)) > 0
        else 0.0
    )
    pieces.append(
        f'<text x="30" y="535" font-family="sans-serif" font-size="12">'
        f'graph repair-cone fraction: {cone_fraction:.4f}</text>'
    )
    (output / "F7_cone_support_residual.svg").write_text(
        svg_frame(
            "F7 — repair cone + screen-space certificate/residual",
            "".join(pieces),
            900,
            570,
        )
    )


def f8(rows: list[dict[str, Any]], output: Path) -> None:
    adversarial = [
        row for row in rows
        if row.get("fallback_full", False)
        or str(row.get("coupling_regime", "")).lower() in {"high", "adversarial"}
    ]
    table = []
    for row in adversarial:
        qoi = next(iter(row["qois"].values()))
        table.append(
            {
                "scene": row.get("scene_id", ""),
                "revision": row.get("revision_id", ""),
                "coupling": row.get("coupling_regime", ""),
                "fallback_full": bool(row.get("fallback_full", False)),
                "candidate_bound": row.get("candidateDiagnostics", {}).get(
                    "candidateRgbBound", ""
                ),
                "epsilon": qoi["epsilon"],
            }
        )
    if table:
        write_csv(output / "F8_adversarial_fallback.csv", list(table[0]), table)
    entries = [
        (f'{item["scene"]}/{item["revision"]}', 1.0 if item["fallback_full"] else 0.0)
        for item in table
    ]
    (output / "F8_adversarial_fallback.svg").write_text(
        bar_svg("F8 — adversarial/high-coupling automatic fallback", entries, "FULL fallback")
    )


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    effects = []
    work_ratios = []
    fallbacks = 0
    violations = 0
    for row in rows:
        fallbacks += int(bool(row.get("fallback_full", False)))
        full = float(row.get("full_work", 0.0))
        work = float(row.get("planner_work", 0.0))
        if full > 0:
            work_ratios.append(work / full)
        for qoi in row["qois"].values():
            actual = float(qoi["measured_full_reference_error"])
            bound = float(qoi["certified_bound"])
            effects.append(bound / max(actual, 1e-15))
            violations += int(actual > bound + 1e-12)
    return {
        "schemaVersion": 1,
        "experiment": "cbrc-paper-analysis-v1",
        "records": len(rows),
        "certificateViolations": violations,
        "fallbackRate": fallbacks / len(rows),
        "medianWorkRatio": statistics.median(work_ratios) if work_ratios else None,
        "medianEffectivity": statistics.median(effects) if effects else None,
        "p95Effectivity": percentile(effects, 0.95) if effects else None,
        "paperFigureReadiness": {
            "F1": True,
            "F2": True,
            "F3": True,
            "F4": True,
            "F5": True,
            "F6": True,
            "F7": False,
            "F8": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--spatial", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    rows = load_rows(args.rows)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    f1(rows, args.output_dir)
    f2(rows, args.output_dir)
    f3(rows, args.output_dir)
    f4(rows, args.output_dir)
    f5(rows, args.output_dir)
    f6(rows, args.output_dir)
    f8(rows, args.output_dir)

    summary = summarize(rows)
    if args.spatial:
        f7(args.spatial, args.output_dir, rows[0])
        summary["paperFigureReadiness"]["F7"] = True
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if summary["certificateViolations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
