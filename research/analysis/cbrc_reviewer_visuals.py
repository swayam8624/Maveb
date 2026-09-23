#!/usr/bin/env python3
"""Create reviewer-facing MAVEB figures with real captured-scene context."""

from __future__ import annotations

import argparse
import io
import json
import math
import zipfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def font(size: int, bold: bool = False):
    candidates = [
        "/System/Library/Fonts/SFNS.ttf",
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
    size = (
        max(1, round(image.width * scale)),
        max(1, round(image.height * scale)),
    )
    resized = image.resize(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (width, height), (247, 248, 250))
    canvas.paste(
        resized,
        ((width - resized.width) // 2, (height - resized.height) // 2),
    )
    return canvas


def placeholder(width: int, height: int, text: str) -> Image.Image:
    image = Image.new("RGB", (width, height), (235, 238, 243))
    draw = ImageDraw.Draw(image)
    draw.text(
        (width / 2, height / 2),
        text,
        font=font(18, True),
        fill=(80, 88, 102),
        anchor="mm",
    )
    return image


def load_render(path: Path) -> Image.Image:
    if not path.is_file():
        raise FileNotFoundError(path)
    return Image.open(path).convert("RGB")


def residual_heat(local: Image.Image, full: Image.Image) -> Image.Image:
    if local.size != full.size:
        raise ValueError("LOCAL/FULL render shape mismatch")
    difference = ImageChops.difference(
        local.convert("RGB"),
        full.convert("RGB"),
    )
    # This is a visualization only. Scientific residual values come from the
    # independent oracle row, not from this colorized image.
    magnitude = ImageOps.autocontrast(difference.convert("L"))
    heat = Image.merge(
        "RGB",
        (
            magnitude,
            magnitude.point(lambda value: int(value * 0.45)),
            magnitude.point(lambda value: int(value * 0.08)),
        ),
    )
    return heat


def import_scene_map(import_manifest: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for dataset in import_manifest.get("datasets", []):
        dataset_id = str(dataset.get("datasetId", ""))
        for scene in dataset.get("scenes", []):
            identifiers = {
                str(scene.get("sceneId", "")),
                str(scene.get("pairId", "")),
            }
            for identifier in identifiers:
                if dataset_id and identifier:
                    result[(dataset_id, identifier)] = scene
    return result


def image_candidates(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    candidates = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in IMAGE_SUFFIXES
        and any(token in path.name.lower() or token in str(path.parent).lower()
                for token in ("rgb", "color", "wide", "frame"))
    ]
    if not candidates:
        candidates = [
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        ]
    return sorted(candidates)


def spaced_pair(paths: list[Path]) -> list[tuple[Image.Image, str]]:
    if not paths:
        return []
    indices = [0] if len(paths) == 1 else [0, len(paths) // 2]
    result: list[tuple[Image.Image, str]] = []
    for index in indices:
        path = paths[index]
        try:
            result.append((Image.open(path).convert("RGB"), str(path)))
        except OSError:
            continue
    return result


def read_bonn(scene: dict[str, Any]) -> list[tuple[Image.Image, str]]:
    root = Path(str(scene.get("root", "")))
    rgb = root / "rgb.txt"
    if rgb.is_file():
        entries: list[Path] = []
        for line in rgb.read_text(errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split()
            if len(parts) >= 2:
                entries.append(root / parts[1])
        return spaced_pair([path for path in entries if path.is_file()])
    return spaced_pair(image_candidates(root))


def read_arkit(scene: dict[str, Any]) -> list[tuple[Image.Image, str]]:
    root = Path(str(scene.get("root", "")))
    preferred = root / "lowres_wide"
    paths = image_candidates(preferred if preferred.is_dir() else root)
    return spaced_pair(paths)


def read_zip_image(path: Path) -> tuple[Image.Image, str] | None:
    if not path.is_file():
        return None
    try:
        with zipfile.ZipFile(path) as archive:
            names = sorted(
                name
                for name in archive.namelist()
                if Path(name).suffix.lower() in IMAGE_SUFFIXES
                and any(token in name.lower() for token in ("color", "rgb", "frame"))
            )
            if not names:
                names = sorted(
                    name
                    for name in archive.namelist()
                    if Path(name).suffix.lower() in IMAGE_SUFFIXES
                )
            if not names:
                return None
            name = names[len(names) // 2]
            data = archive.read(name)
            return Image.open(io.BytesIO(data)).convert("RGB"), f"{path}!{name}"
    except (OSError, zipfile.BadZipFile):
        return None


def read_3rscan(scene: dict[str, Any]) -> list[tuple[Image.Image, str]]:
    result: list[tuple[Image.Image, str]] = []
    for key in ("referenceRoot", "rescanRoot"):
        root_value = scene.get(key)
        if not root_value:
            continue
        root = Path(str(root_value))
        direct = spaced_pair(image_candidates(root))
        if direct:
            result.append(direct[len(direct) // 2])
            continue
        for archive_name in ("sequence.zip", "sequence/sequence.zip"):
            found = read_zip_image(root / archive_name)
            if found is not None:
                result.append(found)
                break
    return result[:2]


def captured_context(
    dataset: str,
    scene: dict[str, Any] | None,
    *,
    width: int,
    height: int,
) -> tuple[Image.Image, list[str]]:
    if scene is None:
        return placeholder(width, height, "source RGB unavailable"), []
    if dataset == "bonn-rgbd-dynamic":
        frames = read_bonn(scene)
    elif dataset == "arkitscenes":
        frames = read_arkit(scene)
    elif dataset == "3rscan":
        frames = read_3rscan(scene)
    else:
        root_value = scene.get("root")
        frames = (
            spaced_pair(image_candidates(Path(str(root_value))))
            if root_value
            else []
        )

    if not frames:
        return placeholder(width, height, "source RGB unavailable"), []

    if len(frames) == 1:
        return fit(frames[0][0], width, height), [frames[0][1]]

    gap = 6
    half = (width - gap) // 2
    context = Image.new("RGB", (width, height), (247, 248, 250))
    context.paste(fit(frames[0][0], half, height), (0, 0))
    context.paste(fit(frames[1][0], width - half - gap, height), (half + gap, 0))
    return context, [frames[0][1], frames[1][1]]


def choose_cases(report: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    nonzero = [
        record
        for record in report.get("records", [])
        if bool(record.get("nonzeroLocal"))
    ]
    nonzero.sort(
        key=lambda record: (
            -float(record.get("actualToEpsilon") or 0.0),
            float(record.get("effectivity") or math.inf),
            record.get("caseId", ""),
        )
    )
    chosen: list[dict[str, Any]] = []
    datasets: set[str] = set()
    for record in nonzero:
        dataset = str(record.get("dataset", ""))
        if dataset not in datasets:
            chosen.append(record)
            datasets.add(dataset)
        if len(chosen) >= limit:
            return chosen
    for record in nonzero:
        if record not in chosen:
            chosen.append(record)
        if len(chosen) >= limit:
            break

    if chosen:
        return chosen

    diagnostic = sorted(
        report.get("records", []),
        key=lambda record: (
            -float(record.get("candidateActual") or 0.0),
            record.get("caseId", ""),
        ),
    )
    return diagnostic[:limit]


def visual_paths(campaign_dir: Path, case_id: str) -> dict[str, Path]:
    root = campaign_dir / "cases" / case_id / "visuals"
    return {
        "before": root / "before.ppm",
        "local": root / "selected-repair.ppm",
        "full": root / "full-after.ppm",
        "support": root / "certified-support.ppm",
    }


def render_case_panel(
    *,
    campaign_dir: Path,
    report: dict[str, Any],
    import_manifest: dict[str, Any],
    output: Path,
) -> dict[str, Any]:
    selected = choose_cases(report, limit=4)
    scene_map = import_scene_map(import_manifest)

    panel_w = 300
    panel_h = 195
    columns = [
        "Captured RGB",
        "Before",
        "LOCAL candidate",
        "FULL rebuild",
        "|LOCAL - FULL|",
        "Certified support",
    ]
    left = 38
    title_h = 115
    row_h = 300
    width = left * 2 + panel_w * len(columns)
    height = title_h + row_h * max(1, len(selected))
    canvas = Image.new("RGB", (width, height), (247, 248, 250))
    draw = ImageDraw.Draw(canvas)

    draw.text(
        (left, 24),
        "MAVEB reviewer evidence: captured context and certified local repair",
        font=font(29, True),
        fill=(18, 22, 30),
    )
    draw.text(
        (left, 65),
        "Captured RGB is dataset source imagery; LOCAL/FULL are independent MAVEB render comparisons.",
        font=font(16),
        fill=(73, 82, 96),
    )
    for index, label in enumerate(columns):
        draw.text(
            (left + index * panel_w + panel_w / 2, 101),
            label,
            font=font(14, True),
            fill=(56, 65, 79),
            anchor="mm",
        )

    manifest_records: list[dict[str, Any]] = []
    for row_index, record in enumerate(selected):
        case_id = str(record["caseId"])
        paths = visual_paths(campaign_dir, case_id)
        before = load_render(paths["before"])
        local = load_render(paths["local"])
        full = load_render(paths["full"])
        support = load_render(paths["support"])
        heat = residual_heat(local, full)

        dataset = str(record.get("dataset", "unknown"))
        scene_id = str(record.get("sourceSceneId", "unknown"))
        source_scene = scene_map.get((dataset, scene_id))
        context, source_paths = captured_context(
            dataset,
            source_scene,
            width=panel_w - 10,
            height=panel_h,
        )

        images = [context, before, local, full, heat, support]
        y = title_h + row_index * row_h
        for column, image in enumerate(images):
            canvas.paste(
                fit(image, panel_w - 10, panel_h),
                (left + column * panel_w + 5, y),
            )

        actual_255 = float(record.get("actual", 0.0)) * 255.0
        bound_255 = float(record.get("bound", 0.0)) * 255.0
        epsilon_255 = float(record.get("epsilon255", 0.0))
        work = record.get("workRatioFull")
        caption = (
            f"{dataset} / {scene_id} / {record.get('editFamily')} / "
            f"{record.get('severityProfile')} | actual={actual_255:.4f}/255 "
            f"<= bound={bound_255:.4f}/255 <= eps={epsilon_255:.2f}/255"
        )
        if work is not None:
            caption += f" | work/FULL={float(work):.3f}"
        draw.text(
            (left + 4, y + panel_h + 13),
            caption,
            font=font(13),
            fill=(19, 24, 34),
        )
        draw.line(
            (left, y + row_h - 15, width - left, y + row_h - 15),
            fill=(216, 221, 230),
            width=2,
        )
        manifest_records.append(
            {
                "caseId": case_id,
                "dataset": dataset,
                "sourceSceneId": scene_id,
                "sourceRgb": source_paths,
                "sourceRgbResolved": bool(source_paths),
                "nonzeroLocal": bool(record.get("nonzeroLocal")),
            }
        )

    if not report.get("certifiedNonzeroLocalCases"):
        draw.rectangle(
            (left, title_h + 4, width - left, title_h + 55),
            fill=(255, 241, 210),
        )
        draw.text(
            (left + 12, title_h + 17),
            "Diagnostic only: no certified non-zero LOCAL result was observed in this frozen run.",
            font=font(17, True),
            fill=(98, 61, 9),
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, quality=96)
    return {
        "figure": str(output),
        "cases": manifest_records,
        "sourceRgbResolvedCases": sum(
            item["sourceRgbResolved"] for item in manifest_records
        ),
    }


def render_crossover(
    report: dict[str, Any],
    output: Path,
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in report.get("records", []):
        groups.setdefault(str(record["stressKey"]), []).append(record)

    candidates = [
        groups[item["stressKey"]]
        for item in report.get("crossoverGroups", [])
        if item["stressKey"] in groups
    ]
    for values in candidates:
        values.sort(key=lambda record: float(record["epsilon255"]))
    candidates.sort(
        key=lambda values: (
            -sum(bool(item.get("nonzeroLocal")) for item in values),
            values[0].get("dataset", ""),
            values[0].get("stressKey", ""),
        )
    )
    selected = candidates[:4]

    width = 1500
    top = 120
    row_h = 230
    height = top + row_h * max(1, len(selected))
    canvas = Image.new("RGB", (width, height), (247, 248, 250))
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (48, 24),
        "Tolerance crossover: identical edit, epsilon changes only",
        font=font(30, True),
        fill=(18, 22, 30),
    )
    draw.text(
        (48, 68),
        "Decision markers are frozen planner outcomes; error and bound are independent FULL-reference evidence.",
        font=font(16),
        fill=(73, 82, 96),
    )

    plot_left = 500
    plot_right = width - 75
    plot_width = plot_right - plot_left
    selected_keys: list[str] = []

    for row_index, values in enumerate(selected):
        first = values[0]
        selected_keys.append(str(first["stressKey"]))
        y_top = top + row_index * row_h
        y_mid = y_top + 95
        draw.text(
            (48, y_top + 20),
            f"{first.get('dataset')} / {first.get('sourceSceneId')}",
            font=font(18, True),
            fill=(24, 29, 38),
        )
        draw.text(
            (48, y_top + 51),
            f"{first.get('editFamily')} / {first.get('severityProfile')}",
            font=font(15),
            fill=(74, 82, 96),
        )

        eps_values = [float(item["epsilon255"]) for item in values]
        minimum = min(eps_values)
        maximum = max(eps_values)
        log_min = math.log2(minimum)
        log_max = math.log2(maximum)
        span = max(log_max - log_min, 1e-9)

        draw.line(
            (plot_left, y_mid, plot_right, y_mid),
            fill=(130, 140, 154),
            width=2,
        )

        for item in values:
            eps = float(item["epsilon255"])
            x = plot_left + (
                (math.log2(eps) - log_min) / span
            ) * plot_width
            local = bool(item.get("local"))
            radius = 12
            fill_color = (40, 120, 75) if local else (155, 74, 55)
            draw.ellipse(
                (x - radius, y_mid - radius, x + radius, y_mid + radius),
                fill=fill_color,
                outline=(30, 34, 42),
                width=2,
            )
            draw.text(
                (x, y_mid + 25),
                f"{eps:g}",
                font=font(12),
                fill=(65, 72, 84),
                anchor="ma",
            )
            if local and float(item.get("actual", 0.0)) > 0.0:
                ratio = float(item.get("actualToEpsilon") or 0.0)
                draw.text(
                    (x, y_mid - 31),
                    f"r={ratio:.2f}",
                    font=font(11, True),
                    fill=(36, 96, 63),
                    anchor="ms",
                )

        draw.text(
            (plot_left, y_top + 16),
            "FULL",
            font=font(13, True),
            fill=(155, 74, 55),
        )
        draw.text(
            (plot_left + 55, y_top + 16),
            "LOCAL",
            font=font(13, True),
            fill=(40, 120, 75),
        )
        draw.text(
            (plot_right, y_mid + 48),
            "epsilon (1/255 units, log2 spacing)",
            font=font(12),
            fill=(84, 91, 104),
            anchor="ra",
        )
        draw.line(
            (48, y_top + row_h - 16, width - 48, y_top + row_h - 16),
            fill=(218, 223, 231),
            width=1,
        )

    if not selected:
        draw.text(
            (width / 2, top + 90),
            "No FULL-to-LOCAL crossover observed in this frozen run.",
            font=font(22, True),
            fill=(100, 62, 12),
            anchor="mm",
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, quality=96)
    return {"figure": str(output), "stressKeys": selected_keys}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--import-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    campaign_dir = args.campaign_dir.resolve()
    report = load_json(args.audit.resolve())
    import_manifest = load_json(args.import_manifest.resolve())
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    panel = render_case_panel(
        campaign_dir=campaign_dir,
        report=report,
        import_manifest=import_manifest,
        output=output_dir / "F_REVIEWER_REAL_SCENE_LOCAL_VS_FULL.png",
    )
    crossover = render_crossover(
        report,
        output_dir / "F_REVIEWER_TOLERANCE_CROSSOVER.png",
    )
    manifest = {
        "schemaVersion": 1,
        "artifact": "maveb-cbrc-reviewer-visual-package",
        "casePanel": panel,
        "crossoverFigure": crossover,
        "scientificBoundary": (
            "Captured RGB panels are original dataset source frames when resolvable. "
            "MAVEB before/LOCAL/FULL panels are renderer outputs of the evaluated "
            "representation. The figure does not claim pixel registration between "
            "source RGB and the MAVEB oracle camera unless separately established."
        ),
    }
    manifest_path = output_dir / "REVIEWER_VISUALS.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
