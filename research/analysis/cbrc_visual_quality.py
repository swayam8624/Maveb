#!/usr/bin/env python3
"""Quantify and visualize rendered revision fidelity for MAVEB/CBRC campaigns.

This audit is intentionally narrow. It compares the selected repair render with
an independently generated FULL-after render produced by the frozen Gaussian
oracle. It also measures the visible before->FULL edit signal so a trivially
unchanged scene cannot masquerade as a high-quality repair.

The output is a graphics-benchmark artifact, not a reconstruction-quality score
against the original camera images. Public RGB/SfM campaigns use seeded
Gaussians; trained-3DGS campaigns use their pinned trained representation.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def load_rows(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def load_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"), dtype=np.uint8)


def metrics(lhs: np.ndarray, rhs: np.ndarray) -> dict[str, Any]:
    if lhs.shape != rhs.shape:
        raise ValueError(f"image shape mismatch: {lhs.shape} != {rhs.shape}")
    delta = lhs.astype(np.int16) - rhs.astype(np.int16)
    abs_delta = np.abs(delta).astype(np.float64)
    mse = float(np.mean(delta.astype(np.float64) ** 2))
    rmse = math.sqrt(mse)
    mae = float(np.mean(abs_delta))
    max_abs = int(np.max(abs_delta)) if abs_delta.size else 0
    exact_pixels = np.all(delta == 0, axis=2)
    exact_fraction = float(np.mean(exact_pixels))
    changed_fraction = 1.0 - exact_fraction
    psnr = None if mse == 0.0 else 20.0 * math.log10(255.0 / rmse)
    return {
        "maeByte": mae,
        "rmseByte": rmse,
        "maxAbsByte": max_abs,
        "exactPixelFraction": exact_fraction,
        "changedPixelFraction": changed_fraction,
        "psnrDb": psnr,
        "psnrInfinite": mse == 0.0,
    }


def image_paths(campaign_dir: Path, case_id: str) -> dict[str, Path]:
    root = campaign_dir / "cases" / case_id / "visuals"
    paths = {
        "before": root / "before.ppm",
        "selected": root / "selected-repair.ppm",
        "full": root / "full-after.ppm",
        "residual": root / "post-repair-residual.ppm",
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing visual evidence: " + ", ".join(missing))
    return paths


def scene_labels(manifest: Path | None) -> dict[str, str]:
    if manifest is None or not manifest.is_file():
        return {}
    payload = json.loads(manifest.read_text())
    result: dict[str, str] = {}
    for key in ("primaryScenes", "campaignV2Scenes"):
        for scene in payload.get(key, []):
            scene_id = str(scene.get("id", ""))
            if not scene_id:
                continue
            dataset = str(scene.get("dataset", "")).strip()
            name = str(scene.get("scene", scene_id)).strip()
            result[scene_id] = f"{dataset} / {name}" if dataset else name
    return result


def evaluate(
    campaign_dir: Path,
    rows: list[dict[str, Any]],
    labels: dict[str, str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    for row in rows:
        case_id = str(row["case_id"])
        paths = image_paths(campaign_dir, case_id)
        before = load_rgb(paths["before"])
        candidate = load_rgb(paths["selected"])
        full = load_rgb(paths["full"])
        fallback = bool(row.get("fallback_full", False))
        # The oracle's selected-repair PPM is the candidate local repair. When
        # the planner falls back, the actual selected execution is FULL, so the
        # final-output fidelity comparison must use the FULL-after image.
        selected = full if fallback else candidate
        selected_full = metrics(selected, full)
        candidate_full = metrics(candidate, full)
        before_full = metrics(before, full)
        scene_id = str(row.get("scene_id", "unknown"))
        scene_label = labels.get(scene_id, scene_id)
        dataset = str(row.get("dataset_id", "")).strip()
        if not dataset:
            dataset = (
                scene_label.split(" / ", 1)[0]
                if " / " in scene_label
                else "unclassified"
            )
        representation = str(row.get("representation", "unknown"))
        edit_family = str(row.get("edit_family", row.get("edit_kind", "unknown")))
        records.append(
            {
                "caseId": case_id,
                "sceneId": scene_id,
                "sceneLabel": scene_label,
                "dataset": dataset,
                "representation": representation,
                "editFamily": edit_family,
                "fallbackFull": fallback,
                "couplingRegime": str(row.get("coupling_regime", "unknown")),
                "workRatioFull": (
                    float(row["planner_work"]) / float(row["full_work"])
                    if float(row.get("full_work", 0.0)) > 0.0
                    else None
                ),
                "selectedVsFull": selected_full,
                "candidateRepairVsFull": candidate_full,
                "selectedImageSource": (
                    "full-after-fallback" if fallback else "candidate-local-repair"
                ),
                "beforeVsFull": before_full,
            }
        )

    if not records:
        raise ValueError("visual-quality audit requires at least one campaign row")

    by_scene: dict[str, dict[str, Any]] = {}
    for scene_id in sorted({record["sceneId"] for record in records}):
        subset = [record for record in records if record["sceneId"] == scene_id]
        by_scene[scene_id] = {
            "label": subset[0]["sceneLabel"],
            "cases": len(subset),
            "localCases": sum(not record["fallbackFull"] for record in subset),
            "fullFallbackCases": sum(record["fallbackFull"] for record in subset),
            "selectedExactCases": sum(
                record["selectedVsFull"]["maxAbsByte"] == 0 for record in subset
            ),
            "medianEditChangedPixelFraction": statistics.median(
                record["beforeVsFull"]["changedPixelFraction"] for record in subset
            ),
            "maximumSelectedVsFullMaxAbsByte": max(
                record["selectedVsFull"]["maxAbsByte"] for record in subset
            ),
        }

    by_dataset: dict[str, dict[str, Any]] = {}
    for dataset in sorted({record["dataset"] for record in records}):
        subset = [record for record in records if record["dataset"] == dataset]
        local_subset = [record for record in subset if not record["fallbackFull"]]
        by_dataset[dataset] = {
            "cases": len(subset),
            "scenes": len({record["sceneId"] for record in subset}),
            "localCases": len(local_subset),
            "fullFallbackCases": sum(record["fallbackFull"] for record in subset),
            "selectedExactCases": sum(
                record["selectedVsFull"]["maxAbsByte"] == 0 for record in subset
            ),
            "localSelectedExactCases": sum(
                record["selectedVsFull"]["maxAbsByte"] == 0 for record in local_subset
            ),
            "maximumSelectedVsFullMaxAbsByte": max(
                record["selectedVsFull"]["maxAbsByte"] for record in subset
            ),
            "medianBeforeVsFullChangedPixelFraction": statistics.median(
                record["beforeVsFull"]["changedPixelFraction"] for record in subset
            ),
        }

    by_edit_family: dict[str, dict[str, Any]] = {}
    for edit_family in sorted({record["editFamily"] for record in records}):
        subset = [record for record in records if record["editFamily"] == edit_family]
        local_subset = [record for record in subset if not record["fallbackFull"]]
        by_edit_family[edit_family] = {
            "cases": len(subset),
            "datasets": len({record["dataset"] for record in subset}),
            "scenes": len({record["sceneId"] for record in subset}),
            "localCases": len(local_subset),
            "fullFallbackCases": sum(record["fallbackFull"] for record in subset),
            "selectedExactCases": sum(
                record["selectedVsFull"]["maxAbsByte"] == 0 for record in subset
            ),
            "localSelectedExactCases": sum(
                record["selectedVsFull"]["maxAbsByte"] == 0 for record in local_subset
            ),
            "maximumSelectedVsFullMaxAbsByte": max(
                record["selectedVsFull"]["maxAbsByte"] for record in subset
            ),
            "medianBeforeVsFullChangedPixelFraction": statistics.median(
                record["beforeVsFull"]["changedPixelFraction"] for record in subset
            ),
        }

    finite_psnr = [
        float(record["selectedVsFull"]["psnrDb"])
        for record in records
        if record["selectedVsFull"]["psnrDb"] is not None
    ]
    edit_changed = [
        float(record["beforeVsFull"]["changedPixelFraction"]) for record in records
    ]
    report = {
        "schemaVersion": 1,
        "artifact": "maveb-cbrc-rendered-visual-quality-audit",
        "rows": len(records),
        "scenes": len(by_scene),
        "localCases": sum(not record["fallbackFull"] for record in records),
        "fullFallbackCases": sum(record["fallbackFull"] for record in records),
        "selectedExactCases": sum(
            record["selectedVsFull"]["maxAbsByte"] == 0 for record in records
        ),
        "selectedExactCaseRate": sum(
            record["selectedVsFull"]["maxAbsByte"] == 0 for record in records
        )
        / len(records),
        "localSelectedExactCases": sum(
            (not record["fallbackFull"])
            and record["selectedVsFull"]["maxAbsByte"] == 0
            for record in records
        ),
        "localSelectedExactCaseRate": (
            sum(
                (not record["fallbackFull"])
                and record["selectedVsFull"]["maxAbsByte"] == 0
                for record in records
            )
            / max(1, sum(not record["fallbackFull"] for record in records))
        ),
        "maximumSelectedVsFullMaxAbsByte": max(
            record["selectedVsFull"]["maxAbsByte"] for record in records
        ),
        "maximumSelectedVsFullMaeByte": max(
            record["selectedVsFull"]["maeByte"] for record in records
        ),
        "minimumFiniteSelectedVsFullPsnrDb": min(finite_psnr)
        if finite_psnr
        else None,
        "allSelectedVsFullPsnrInfinite": not finite_psnr,
        "medianBeforeVsFullChangedPixelFraction": statistics.median(edit_changed),
        "minimumBeforeVsFullChangedPixelFraction": min(edit_changed),
        "maximumBeforeVsFullChangedPixelFraction": max(edit_changed),
        "byScene": by_scene,
        "byDataset": by_dataset,
        "byEditFamily": by_edit_family,
        "scientificBoundary": (
            "Selected-vs-FULL metrics measure fidelity to the independent FULL-after "
            "oracle render for the evaluated representation. They are not photorealistic "
            "reconstruction-quality metrics against original held-out camera images. "
            "Public RGB/SfM scenes use seeded Gaussians; trained-3DGS runs evaluate the "
            "pinned trained representation."
        ),
        "records": records,
    }
    return report, records


def font(size: int, bold: bool = False):
    candidates = [
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                pass
    return ImageFont.load_default()


def fit(image: Image.Image, width: int, height: int) -> Image.Image:
    image = image.convert("RGB")
    scale = min(width / image.width, height / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    resized = image.resize(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (width, height), (247, 248, 250))
    canvas.paste(resized, ((width - resized.width) // 2, (height - resized.height) // 2))
    return canvas


def residual_heat(selected: np.ndarray, full: np.ndarray) -> Image.Image:
    delta = np.max(
        np.abs(selected.astype(np.int16) - full.astype(np.int16)),
        axis=2,
    ).astype(np.float32)
    if float(delta.max()) <= 0.0:
        rgb = np.zeros((*delta.shape, 3), dtype=np.uint8)
    else:
        t = np.clip(delta / float(delta.max()), 0.0, 1.0)
        rgb = np.stack(
            [
                np.clip(255.0 * (2.0 * t), 0, 255),
                np.clip(255.0 * (1.4 * t), 0, 255),
                np.clip(255.0 * (0.25 * (1.0 - t)), 0, 255),
            ],
            axis=2,
        ).astype(np.uint8)
    return Image.fromarray(rgb, mode="RGB")


def choose_representatives(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chosen = []
    for scene_id in sorted({record["sceneId"] for record in records}):
        subset = [record for record in records if record["sceneId"] == scene_id]
        local = [record for record in subset if not record["fallbackFull"]]
        pool = local if local else subset
        chosen.append(
            max(
                pool,
                key=lambda record: record["beforeVsFull"]["changedPixelFraction"],
            )
        )
    return chosen


def render_grid(
    campaign_dir: Path,
    records: list[dict[str, Any]],
    output: Path,
) -> list[str]:
    selected = choose_representatives(records)
    panel_w, panel_h = 420, 240
    left = 60
    title_h = 120
    row_h = 355
    columns = ["Before", "Selected repair", "FULL-after", "Selected − FULL"]
    canvas = Image.new(
        "RGB",
        (left * 2 + panel_w * 4, title_h + row_h * len(selected)),
        (247, 248, 250),
    )
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (left, 32),
        "MAVEB benchmark visual fidelity — selected repair vs independent FULL-after",
        fill=(16, 19, 26),
        font=font(34, True),
    )
    for col, label in enumerate(columns):
        draw.text(
            (left + col * panel_w + panel_w / 2, 86),
            label,
            fill=(71, 84, 103),
            font=font(18, True),
            anchor="mm",
        )

    ids: list[str] = []
    for row_index, record in enumerate(selected):
        ids.append(record["caseId"])
        paths = image_paths(campaign_dir, record["caseId"])
        before = Image.open(paths["before"]).convert("RGB")
        candidate_img = Image.open(paths["selected"]).convert("RGB")
        full = Image.open(paths["full"]).convert("RGB")
        selected_img = full.copy() if record["fallbackFull"] else candidate_img
        heat = residual_heat(np.asarray(selected_img), np.asarray(full))
        images = [before, selected_img, full, heat]
        y = title_h + row_index * row_h
        for col, image in enumerate(images):
            canvas.paste(fit(image, panel_w - 12, panel_h), (left + col * panel_w + 6, y))
        metric = record["selectedVsFull"]
        edit = record["beforeVsFull"]
        state = "FULL fallback" if record["fallbackFull"] else "LOCAL"
        caption = (
            f'{record["sceneLabel"]} · {state} · case {record["caseId"]} · '
            f'final selected↔FULL max |Δ|={metric["maxAbsByte"]}/255, '
            f'exact pixels={metric["exactPixelFraction"]:.3%} · '
            f'edited pixels={edit["changedPixelFraction"]:.3%}'
        )
        draw.text(
            (left + 8, y + panel_h + 18),
            caption,
            fill=(16, 19, 26),
            font=font(16, False),
        )
        draw.line(
            (left, y + row_h - 10, canvas.width - left, y + row_h - 10),
            fill=(216, 222, 233),
            width=2,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, quality=95)
    return ids


def write_csv(records: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "case_id",
                "scene_id",
                "scene_label",
                "dataset",
                "representation",
                "edit_family",
                "fallback_full",
                "coupling_regime",
                "work_ratio_full",
                "selected_vs_full_mae_byte",
                "selected_vs_full_rmse_byte",
                "selected_vs_full_max_abs_byte",
                "selected_vs_full_exact_pixel_fraction",
                "selected_vs_full_psnr_db",
                "selected_vs_full_psnr_infinite",
                "before_vs_full_changed_pixel_fraction",
                "before_vs_full_max_abs_byte",
            ],
        )
        writer.writeheader()
        for record in records:
            selected = record["selectedVsFull"]
            edit = record["beforeVsFull"]
            writer.writerow(
                {
                    "case_id": record["caseId"],
                    "scene_id": record["sceneId"],
                    "scene_label": record["sceneLabel"],
                    "dataset": record["dataset"],
                    "representation": record["representation"],
                    "edit_family": record["editFamily"],
                    "fallback_full": record["fallbackFull"],
                    "coupling_regime": record["couplingRegime"],
                    "work_ratio_full": record["workRatioFull"],
                    "selected_vs_full_mae_byte": selected["maeByte"],
                    "selected_vs_full_rmse_byte": selected["rmseByte"],
                    "selected_vs_full_max_abs_byte": selected["maxAbsByte"],
                    "selected_vs_full_exact_pixel_fraction": selected["exactPixelFraction"],
                    "selected_vs_full_psnr_db": selected["psnrDb"],
                    "selected_vs_full_psnr_infinite": selected["psnrInfinite"],
                    "before_vs_full_changed_pixel_fraction": edit["changedPixelFraction"],
                    "before_vs_full_max_abs_byte": edit["maxAbsByte"],
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=Path("research/config/cbrc_public_real_sources.json"),
    )
    args = parser.parse_args()

    campaign_dir = args.campaign_dir.resolve()
    output_dir = args.output_dir.resolve()
    rows = load_rows(campaign_dir / "campaign-rows.jsonl")
    labels = scene_labels(args.source_manifest)
    report, records = evaluate(campaign_dir, rows, labels)
    representatives = render_grid(
        campaign_dir,
        records,
        output_dir / "F13_benchmark_visual_quality.png",
    )
    report["representativeCases"] = representatives
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "CBRC_VISUAL_QUALITY.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    write_csv(records, output_dir / "CBRC_VISUAL_QUALITY.csv")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
