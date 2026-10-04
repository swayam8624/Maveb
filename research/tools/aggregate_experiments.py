#!/usr/bin/env python3
"""Aggregate MAVEB research runs into reproducible metric tables and Pareto fronts.

The tool is intentionally schema-tolerant at the file-discovery boundary but strict once a file
declares schemaVersion=1 and experiment_id. It never invents missing metrics. Missing values remain
null and are excluded only from the specific Pareto comparison that requires them.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class Objective:
    path: str
    direction: str  # "min" or "max"


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def nested(data: dict[str, Any], dotted: str) -> Any:
    current: Any = data
    for key in dotted.split("."):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def discover(paths: Iterable[Path]) -> list[tuple[Path, dict[str, Any]]]:
    rows: list[tuple[Path, dict[str, Any]]] = []
    for root in paths:
        candidates = [root] if root.is_file() else sorted(root.rglob("*.json"))
        for path in candidates:
            try:
                data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict) or data.get("schemaVersion") != 1:
                continue
            if "experiment_id" not in data and "experimentId" not in data:
                continue
            rows.append((path, data))
    return rows


def experiment_id(data: dict[str, Any]) -> str:
    value = data.get("experiment_id", data.get("experimentId"))
    if not isinstance(value, str) or not value:
        raise ValueError("experiment_id must be a non-empty string")
    return value


def flatten_selected(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    locality = data.get("locality", {}).get("domains", {})
    row: dict[str, Any] = {
        "experiment_id": experiment_id(data),
        "source": str(path),
        "git_sha": data.get("git_sha", data.get("gitSha")),
        "dataset": data.get("dataset"),
        "scene": data.get("scene"),
        "seed": data.get("seed"),
        "changed_fraction": data.get("changed_fraction", data.get("changedFraction")),
        "psnr": nested(data, "quality.psnr"),
        "ssim": nested(data, "quality.ssim"),
        "lpips": nested(data, "quality.lpips"),
        "depth_rmse": nested(data, "geometry.depth_rmse"),
        "change_iou": nested(data, "continual.change_iou"),
        "identity_survival": nested(data, "continual.identity_survival"),
        "unchanged_damage": nested(data, "continual.unchanged_damage"),
        "gpu_p50_ms": nested(data, "performance.gpu_p50_ms"),
        "gpu_p95_ms": nested(data, "performance.gpu_p95_ms"),
        "gpu_p99_ms": nested(data, "performance.gpu_p99_ms"),
        "cpu_ms": nested(data, "performance.cpu_ms"),
        "peak_memory_mb": nested(data, "performance.peak_memory_mb"),
    }
    if isinstance(locality, dict):
        for name, counter in sorted(locality.items()):
            if isinstance(counter, dict):
                row[f"ulr_{name}"] = counter.get("ratio")
    return row


def dominates(a: dict[str, Any], b: dict[str, Any], objectives: list[Objective]) -> bool:
    strictly_better = False
    for objective in objectives:
        av = finite_number(nested(a, objective.path))
        bv = finite_number(nested(b, objective.path))
        if av is None or bv is None:
            return False
        if objective.direction == "min":
            if av > bv:
                return False
            strictly_better = strictly_better or av < bv
        elif objective.direction == "max":
            if av < bv:
                return False
            strictly_better = strictly_better or av > bv
        else:
            raise ValueError(f"invalid objective direction: {objective.direction}")
    return strictly_better


def pareto_front(runs: list[dict[str, Any]], objectives: list[Objective]) -> list[str]:
    ids: list[str] = []
    for i, candidate in enumerate(runs):
        if any(
            j != i and dominates(other, candidate, objectives)
            for j, other in enumerate(runs)
        ):
            continue
        ids.append(experiment_id(candidate))
    return sorted(ids)


def robust_outliers(rows: list[dict[str, Any]], key: str, z_threshold: float = 3.5) -> list[str]:
    values = [
        (row["experiment_id"], finite_number(row.get(key)))
        for row in rows
    ]
    values = [(identifier, value) for identifier, value in values if value is not None]
    if len(values) < 5:
        return []
    numeric = sorted(value for _, value in values)
    median = numeric[len(numeric) // 2]
    deviations = sorted(abs(value - median) for value in numeric)
    mad = deviations[len(deviations) // 2]
    if mad <= 1e-15:
        return []
    result = []
    for identifier, value in values:
        modified_z = 0.6745 * (value - median) / mad
        if abs(modified_z) > z_threshold:
            result.append(identifier)
    return sorted(result)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def write_dashboard(path: Path, rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    headers = [
        "experiment_id", "dataset", "scene", "changed_fraction", "psnr", "gpu_p95_ms",
        "peak_memory_mb",
    ]
    body = []
    for row in rows:
        cells = "".join(
            f"<td>{'' if row.get(key) is None else row.get(key)}</td>" for key in headers
        )
        body.append(f"<tr>{cells}</tr>")
    html = (
        "<!doctype html><meta charset='utf-8'><title>MAVEB research dashboard</title>"
        "<style>body{font-family:system-ui;max-width:1200px;margin:2rem auto;padding:0 1rem}"
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccc;padding:.4rem}"
        "th{text-align:left}code{white-space:pre-wrap}</style>"
        "<h1>MAVEB research dashboard</h1>"
        f"<p>Runs: <strong>{len(rows)}</strong></p>"
        "<h2>Pareto front</h2><code>"
        + json.dumps(summary.get("pareto", []), indent=2)
        + "</code><h2>Runs</h2><table><thead><tr>"
        + "".join(f"<th>{key}</th>" for key in headers)
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(html)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    discovered = discover(args.paths)
    raw = [data for _, data in discovered]
    rows = [flatten_selected(path, data) for path, data in discovered]
    objectives = [
        Objective("performance.gpu_p95_ms", "min"),
        Objective("performance.peak_memory_mb", "min"),
        Objective("quality.psnr", "max"),
    ]
    summary = {
        "schemaVersion": 1,
        "runCount": len(rows),
        "paretoObjectives": [
            {"path": objective.path, "direction": objective.direction}
            for objective in objectives
        ],
        "pareto": pareto_front(raw, objectives) if raw else [],
        "gpuP95Outliers": robust_outliers(rows, "gpu_p95_ms"),
    }
    write_csv(args.output_dir / "runs.csv", rows)
    write_json(args.output_dir / "summary.json", summary)
    write_dashboard(args.output_dir / "index.html", rows, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
