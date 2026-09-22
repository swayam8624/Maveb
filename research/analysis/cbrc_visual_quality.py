#!/usr/bin/env python3
"""Image-space benchmark audit for MAVEB/CBRC campaign outputs.

The audit compares the selected repair against the independent FULL-after render
and separately measures whether the underlying edit was visually non-trivial.
It operates only on frozen campaign rows and oracle-rendered PPM files.

Outputs:
  * visual-quality.json
  * visual-quality.csv
  * VISUAL_QUALITY.md
  * visual-quality-mosaic.png

No learned perceptual model is used. Metrics are deliberately simple and fully
reproducible: MAE, RMSE, L_inf, PSNR, exact-pixel agreement, and changed-pixel
fraction in normalized RGB space.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont


@dataclass
class PairMetrics:
    mae: float
    rmse: float
    linf: float
    psnr_db: float | None
    exact_pixel_fraction: float
    changed_pixel_fraction: float


def load_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"), dtype=np.float64) / 255.0


def pair_metrics(a: np.ndarray, b: np.ndarray) -> PairMetrics:
    if a.shape != b.shape:
        raise ValueError(f"image shape mismatch: {a.shape} != {b.shape}")
    diff = np.abs(a - b)
    per_pixel_max = diff.max(axis=2)
    mse = float(np.mean((a - b) ** 2))
    rmse = math.sqrt(mse)
    psnr = None if mse == 0.0 else 10.0 * math.log10(1.0 / mse)
    return PairMetrics(
        mae=float(np.mean(diff)),
        rmse=rmse,
        linf=float(np.max(diff)),
        psnr_db=psnr,
        exact_pixel_fraction=float(np.mean(per_pixel_max == 0.0)),
        changed_pixel_fraction=float(np.mean(per_pixel_max > 0.0)),
    )


def metrics_for_case(campaign_dir: Path, row: dict[str, Any]) -> dict[str, Any]:
    case_id = str(row["case_id"])
    root = campaign_dir / "cases" / case_id / "visuals"
    before = load_rgb(root / "before.ppm")
    full_after = load_rgb(root / "full-after.ppm")
    selected = load_rgb(root / "selected-repair.ppm")

    selected_vs_full = pair_metrics(selected, full_after)
    before_vs_full = pair_metrics(before, full_after)
    qoi = row.get("qois", {}).get("rgb_linf", {})
    full_work = float(row.get("full_work", 0.0))
    return {
        "case_id": case_id,
        "scene_id": str(row.get("scene_id", "")),
        "coupling_regime": str(row.get("coupling_regime", "")),
        "decision": "FULL" if bool(row.get("fallback_full", False)) else "LOCAL",
        "work_ratio_full": (
            0.0 if full_work <= 0.0
            else float(row.get("planner_work", 0.0)) / full_work
        ),
        "selected_vs_full": asdict(selected_vs_full),
        "before_vs_full": asdict(before_vs_full),
        "certificate_rgb_linf": {
            "epsilon": float(qoi.get("epsilon", 0.0)),
            "bound": float(qoi.get("certified_bound", 0.0)),
            "measured_full_reference_error": float(
                qoi.get("measured_full_reference_error", 0.0)
            ),
        },
    }


def finite_median(values: list[float | None]) -> float | None:
    finite = [
        float(value)
        for value in values
        if value is not None and math.isfinite(float(value))
    ]
    return None if not finite else float(statistics.median(finite))


def aggregate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    if not cases:
        raise ValueError("visual-quality audit requires at least one case")
    scenes = sorted({case["scene_id"] for case in cases})
    local = [case for case in cases if case["decision"] == "LOCAL"]
    full = [case for case in cases if case["decision"] == "FULL"]
    exact_cases = [
        case for case in cases
        if case["selected_vs_full"]["linf"] == 0.0
    ]
    visually_changed = [
        case for case in cases
        if case["before_vs_full"]["changed_pixel_fraction"] > 0.0
    ]
    nontrivial = [
        case for case in cases
        if case["before_vs_full"]["linf"] > 0.0
    ]
    return {
        "case_count": len(cases),
        "scene_count": len(scenes),
        "scenes": scenes,
        "local_cases": len(local),
        "full_cases": len(full),
        "selected_matches_full_exactly": len(exact_cases),
        "selected_matches_full_exactly_rate": len(exact_cases) / len(cases),
        "cases_with_visible_pixel_change": len(visually_changed),
        "cases_with_visible_pixel_change_rate": len(visually_changed) / len(cases),
        "cases_with_nonzero_before_after_linf": len(nontrivial),
        "median_selected_vs_full_mae": float(
            statistics.median(
                case["selected_vs_full"]["mae"] for case in cases
            )
        ),
        "max_selected_vs_full_linf": float(
            max(case["selected_vs_full"]["linf"] for case in cases)
        ),
        "median_selected_vs_full_psnr_db_finite": finite_median(
            [case["selected_vs_full"]["psnr_db"] for case in cases]
        ),
        "median_before_vs_full_changed_pixel_fraction": float(
            statistics.median(
                case["before_vs_full"]["changed_pixel_fraction"]
                for case in cases
            )
        ),
        "median_before_vs_full_linf": float(
            statistics.median(
                case["before_vs_full"]["linf"] for case in cases
            )
        ),
    }


def save_csv(cases: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "case_id", "scene_id", "coupling_regime", "decision",
        "work_ratio_full", "selected_mae", "selected_rmse",
        "selected_linf", "selected_psnr_db",
        "selected_exact_pixel_fraction", "selected_changed_pixel_fraction",
        "edit_mae", "edit_rmse", "edit_linf", "edit_psnr_db",
        "edit_exact_pixel_fraction", "edit_changed_pixel_fraction",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for case in cases:
            selected = case["selected_vs_full"]
            edit = case["before_vs_full"]
            writer.writerow(
                {
                    "case_id": case["case_id"],
                    "scene_id": case["scene_id"],
                    "coupling_regime": case["coupling_regime"],
                    "decision": case["decision"],
                    "work_ratio_full": case["work_ratio_full"],
                    "selected_mae": selected["mae"],
                    "selected_rmse": selected["rmse"],
                    "selected_linf": selected["linf"],
                    "selected_psnr_db": (
                        "inf"
                        if selected["psnr_db"] is None
                        else selected["psnr_db"]
                    ),
                    "selected_exact_pixel_fraction":
                        selected["exact_pixel_fraction"],
                    "selected_changed_pixel_fraction":
                        selected["changed_pixel_fraction"],
                    "edit_mae": edit["mae"],
                    "edit_rmse": edit["rmse"],
                    "edit_linf": edit["linf"],
                    "edit_psnr_db": (
                        "inf" if edit["psnr_db"] is None else edit["psnr_db"]
                    ),
                    "edit_exact_pixel_fraction": edit["exact_pixel_fraction"],
                    "edit_changed_pixel_fraction":
                        edit["changed_pixel_fraction"],
                }
            )


def save_markdown(report: dict[str, Any], path: Path) -> None:
    aggregate_data = report["aggregate"]
    lines = [
        "# MAVEB visual-quality benchmark audit",
        "",
        (
            "This audit compares the selected MAVEB result against the independent "
            "FULL-after oracle render and separately measures the visible magnitude "
            "of the underlying edit. It uses only frozen campaign outputs; it does "
            "not add or synthesize scene evidence."
        ),
        "",
        (
            f"- Cases: **{aggregate_data['case_count']}** across "
            f"**{aggregate_data['scene_count']}** public scenes."
        ),
        (
            f"- Decisions: **{aggregate_data['local_cases']} LOCAL / "
            f"{aggregate_data['full_cases']} FULL**."
        ),
        (
            "- Selected render exactly matches FULL-after at 8-bit oracle precision "
            f"in **{aggregate_data['selected_matches_full_exactly']}/"
            f"{aggregate_data['case_count']}** cases."
        ),
        (
            "- Cases with at least one changed RGB pixel from before -> FULL-after: "
            f"**{aggregate_data['cases_with_visible_pixel_change']}/"
            f"{aggregate_data['case_count']}**."
        ),
        (
            "- Median before -> FULL-after changed-pixel fraction: "
            f"**{100.0 * aggregate_data['median_before_vs_full_changed_pixel_fraction']:.3f}%**."
        ),
        (
            "- Median before -> FULL-after RGB L_inf: "
            f"**{aggregate_data['median_before_vs_full_linf']:.6f}** "
            "on normalized [0,1] RGB."
        ),
        (
            "- Maximum selected -> FULL-after RGB L_inf: "
            f"**{aggregate_data['max_selected_vs_full_linf']:.6g}**."
        ),
        "",
        (
            "Interpretation boundary: exact equality here is equality of the frozen "
            "8-bit oracle renders, not a claim of perceptual equivalence outside the "
            "tested views or of photorealistic reconstruction quality. Visual-quality "
            "figures should be read together with the dataset/representation scope in "
            "the manuscript."
        ),
        "",
    ]
    path.write_text("\n".join(lines))


def font(size: int, bold: bool = False):
    candidates = [
        (
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
            if bold
            else "/System/Library/Fonts/Supplemental/Arial.ttf"
        ),
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ),
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def representative_cases(
    cases: list[dict[str, Any]], maximum: int = 6
) -> list[dict[str, Any]]:
    ordered = sorted(
        cases,
        key=lambda case: case["before_vs_full"]["changed_pixel_fraction"],
        reverse=True,
    )
    result: list[dict[str, Any]] = []
    seen_scene_decision: set[tuple[str, str]] = set()
    for case in ordered:
        key = (case["scene_id"], case["decision"])
        if key not in seen_scene_decision:
            result.append(case)
            seen_scene_decision.add(key)
        if len(result) >= maximum:
            return result
    for case in ordered:
        if case not in result:
            result.append(case)
        if len(result) >= maximum:
            break
    return result


def save_mosaic(
    campaign_dir: Path,
    cases: list[dict[str, Any]],
    path: Path,
) -> None:
    chosen = representative_cases(cases)
    panel_width, panel_height = 340, 210
    row_height = 285
    canvas = Image.new(
        "RGB",
        (panel_width * 4 + 80, 90 + row_height * len(chosen)),
        "white",
    )
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (35, 25),
        "MAVEB visual-quality benchmark: selected repair vs FULL-after",
        fill="black",
        font=font(28, True),
    )
    labels = ["Before", "Selected repair", "FULL-after", "|Selected - FULL|"]
    for index, label in enumerate(labels):
        draw.text(
            (40 + index * panel_width, 66),
            label,
            fill=(70, 70, 70),
            font=font(15, True),
        )

    for row_index, case in enumerate(chosen):
        y = 92 + row_index * row_height
        root = campaign_dir / "cases" / case["case_id"] / "visuals"
        before = Image.open(root / "before.ppm").convert("RGB")
        selected = Image.open(root / "selected-repair.ppm").convert("RGB")
        full_after = Image.open(root / "full-after.ppm").convert("RGB")
        selected_array = np.asarray(selected, dtype=np.int16)
        full_array = np.asarray(full_after, dtype=np.int16)
        difference = np.abs(selected_array - full_array)
        difference_display = Image.fromarray(
            np.clip(difference * 8, 0, 255).astype(np.uint8),
            "RGB",
        )
        images = [before, selected, full_after, difference_display]
        for column, image in enumerate(images):
            thumbnail = image.copy()
            thumbnail.thumbnail(
                (panel_width - 18, panel_height - 18),
                Image.Resampling.LANCZOS,
            )
            x = (
                40
                + column * panel_width
                + (panel_width - thumbnail.width) // 2
            )
            image_y = y + (panel_height - thumbnail.height) // 2
            canvas.paste(thumbnail, (x, image_y))

        selected_metrics = case["selected_vs_full"]
        caption = (
            f"{case['scene_id']} | {case['decision']} | "
            f"work/FULL {case['work_ratio_full']:.3f} | "
            f"selected->FULL L_inf {selected_metrics['linf']:.3g}"
        )
        draw.text(
            (40, y + panel_height + 12),
            caption,
            fill="black",
            font=font(15),
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)


def audit(campaign_dir: Path) -> dict[str, Any]:
    rows = load_rows(campaign_dir / "campaign-rows.jsonl")
    cases = [metrics_for_case(campaign_dir, row) for row in rows]
    return {
        "schemaVersion": 1,
        "artifact": "maveb-cbrc-visual-quality-audit",
        "metricSpace": "8-bit oracle RGB normalized to [0,1]",
        "psnrConvention": "null means +infinity because MSE is exactly zero",
        "aggregate": aggregate(cases),
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    campaign = args.campaign_dir.resolve()
    output = args.output_dir.resolve()
    report = audit(campaign)
    output.mkdir(parents=True, exist_ok=True)
    (output / "visual-quality.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    save_csv(report["cases"], output / "visual-quality.csv")
    save_markdown(report, output / "VISUAL_QUALITY.md")
    save_mosaic(
        campaign,
        report["cases"],
        output / "visual-quality-mosaic.png",
    )
    print(json.dumps(report["aggregate"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
