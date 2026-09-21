#!/usr/bin/env python3
"""Generate reproducible SIGGRAPH-style MAVEB visual assets from campaign evidence.

Inputs are only frozen campaign artifacts and oracle-rendered PPMs. The script
does not invent scene content or alter measured values. It creates:
  * a paper hero figure,
  * a safety/work/baseline summary sheet,
  * a local-vs-FULL fallback case mosaic,
  * an animated teaser GIF,
  * a supplementary animated GIF,
  * a vector system-overview SVG,
  * a shot manifest for external video editing.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


THEME = {
    "paper": (247, 248, 250),
    "ink": (16, 19, 26),
    "muted": (102, 112, 133),
    "grid": (216, 222, 233),
    "edit": (255, 138, 52),
    "certificate": (24, 198, 217),
    "local": (40, 199, 111),
    "fallback": (240, 68, 56),
    "residual": (229, 72, 77),
    "accent": (124, 92, 252),
    "full": (71, 84, 103),
    "white": (255, 255, 255),
}


def load_rows(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def font(size: int, bold: bool = False):
    candidates = (
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
        if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                pass
    return ImageFont.load_default()


def text(draw: ImageDraw.ImageDraw, xy, value: str, size: int, fill=None, bold=False, anchor=None):
    draw.text(
        xy,
        value,
        font=font(size, bold=bold),
        fill=fill or THEME["ink"],
        anchor=anchor,
    )


def fit(image: Image.Image, width: int, height: int) -> Image.Image:
    source = image.convert("RGB")
    scale = max(width / source.width, height / source.height)
    resized = source.resize(
        (max(1, round(source.width * scale)), max(1, round(source.height * scale))),
        Image.Resampling.LANCZOS,
    )
    left = max(0, (resized.width - width) // 2)
    top = max(0, (resized.height - height) // 2)
    return resized.crop((left, top, left + width, top + height))


def card(canvas: Image.Image, box, radius=18, fill=None, outline=None):
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(
        box,
        radius=radius,
        fill=fill or THEME["white"],
        outline=outline or THEME["grid"],
        width=2,
    )


def case_visuals(campaign_dir: Path, case_id: str) -> dict[str, Image.Image]:
    root = campaign_dir / "cases" / case_id / "visuals"
    names = {
        "before": "before.ppm",
        "after": "full-after.ppm",
        "repair": "selected-repair.ppm",
        "support": "certified-support.ppm",
        "effect": "edit-effect.ppm",
        "residual": "post-repair-residual.ppm",
    }
    result = {}
    for key, name in names.items():
        path = root / name
        if not path.is_file():
            raise FileNotFoundError(path)
        result[key] = Image.open(path).convert("RGB")
    return result


def work_ratio(row: dict[str, Any]) -> float:
    full = float(row["full_work"])
    return 0.0 if full <= 0 else float(row["planner_work"]) / full


def case_label(row: dict[str, Any]) -> str:
    return f'{row.get("scene_id","scene")} · {row.get("coupling_regime","unknown")}'


def badge(draw, box, label, color):
    draw.rounded_rectangle(box, radius=14, fill=color)
    text(
        draw,
        ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2),
        label,
        22,
        THEME["white"],
        bold=True,
        anchor="mm",
    )


def hero(rows: list[dict[str, Any]], campaign_dir: Path, output: Path) -> dict[str, str]:
    local = next((row for row in rows if not row.get("fallback_full", False)), None)
    fallback = next((row for row in rows if row.get("fallback_full", False)), None)
    if local is None:
        raise ValueError("hero requires at least one certified local case")
    if fallback is None:
        raise ValueError("hero requires at least one FULL fallback case")

    canvas = Image.new("RGB", (2800, 1680), THEME["paper"])
    draw = ImageDraw.Draw(canvas)
    text(draw, (100, 78), "MAVEB — Certified Local Revision of Persistent Gaussian Worlds", 54, bold=True)
    text(
        draw,
        (100, 148),
        "Repair only what must change. Prove the residual. Fall back to FULL when locality is unsafe.",
        28,
        THEME["muted"],
    )

    columns = [
        ("before", "Before"),
        ("effect", "Intended edit"),
        ("support", "Certified support"),
        ("repair", "Selected repair"),
        ("after", "FULL-after"),
        ("residual", "Post-repair residual"),
    ]
    panel_w, panel_h = 410, 330
    gap = 35
    x0 = 100

    def draw_row(row: dict[str, Any], y: int, title_value: str, status: str, color):
        visuals = case_visuals(campaign_dir, str(row["case_id"]))
        text(draw, (100, y - 55), title_value, 32, bold=True)
        text(draw, (100, y - 15), case_label(row), 20, THEME["muted"])
        badge(draw, (2260, y - 58, 2670, y - 8), status, color)

        for i, (key, label) in enumerate(columns):
            x = x0 + i * (panel_w + gap)
            card(canvas, (x - 8, y - 8, x + panel_w + 8, y + panel_h + 56))
            canvas.paste(fit(visuals[key], panel_w, panel_h), (x, y))
            text(draw, (x + panel_w / 2, y + panel_h + 27), label, 19, anchor="mm")

        ratio = work_ratio(row)
        diag = row.get("candidateDiagnostics", {})
        stats_y = y + panel_h + 96
        stats = [
            f"selected work/FULL  {ratio:.3%}",
            f"work reduction  {1/ratio:.1f}×" if ratio > 0 else "work reduction  ∞",
            f"updated Gaussians  {row.get('changed_fraction',0):.3%}",
            f"residual  {row['qois']['rgb_linf']['measured_full_reference_error']:.2e}",
            f"certified bound  {row['qois']['rgb_linf']['certified_bound']:.2e}",
            f"raw edit effect  {float(diag.get('sourceEditActualRgbError',0)):.3g}",
        ]
        for j, value in enumerate(stats):
            sx = 100 + j * 430
            text(draw, (sx, stats_y), value, 20, THEME["ink"], bold=(j < 2))

    draw_row(local, 280, "Certified local revision", "LOCAL / CERTIFIED", THEME["local"])
    draw_row(fallback, 985, "High-coupling / unstable revision", "AUTOMATIC FULL FALLBACK", THEME["fallback"])

    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, quality=95)
    return {"local": str(local["case_id"]), "fallback": str(fallback["case_id"])}


def chart_sheet(
    rows: list[dict[str, Any]],
    baseline_summary: dict[str, Any],
    output: Path,
):
    canvas = Image.new("RGB", (2200, 1500), THEME["paper"])
    draw = ImageDraw.Draw(canvas)
    text(draw, (90, 70), "MAVEB evidence dashboard", 48, bold=True)

    # Safety scatter.
    x0, y0, w, h = 100, 200, 850, 520
    card(canvas, (70, 155, 1000, 770))
    text(draw, (100, 190), "Safety: measured residual ≤ certified bound", 28, bold=True)
    values = []
    maxv = 1e-12
    for row in rows:
        qoi = row["qois"]["rgb_linf"]
        actual = float(qoi["measured_full_reference_error"])
        bound = float(qoi["certified_bound"])
        values.append((actual, bound, bool(row.get("fallback_full", False))))
        maxv = max(maxv, actual, bound)
    margin = 70
    px0, py0 = x0 + margin, y0 + h - margin
    pw, ph = w - 2 * margin, h - 2 * margin
    draw.line((px0, py0, px0 + pw, py0 - ph), fill=THEME["grid"], width=4)
    draw.line((px0, py0, px0 + pw, py0), fill=THEME["ink"], width=3)
    draw.line((px0, py0, px0, py0 - ph), fill=THEME["ink"], width=3)
    for actual, bound, fallback in values:
        x = px0 + (actual / maxv) * pw
        y = py0 - (bound / maxv) * ph
        color = THEME["fallback"] if fallback else THEME["certificate"]
        draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=color)
    text(draw, (px0 + pw / 2, py0 + 38), "measured post-repair residual", 19, anchor="mm")
    text(draw, (px0, py0 - ph - 25), f"max axis = {maxv:.2e}", 17, THEME["muted"])

    # Work ratios.
    card(canvas, (1070, 155, 2130, 770))
    text(draw, (1100, 190), "Native work domains", 28, bold=True)
    domains: dict[str, list[float]] = {}
    for row in rows:
        for name, counter in row.get("work_ledger", {}).get("domains", {}).items():
            full = float(counter.get("full", 0))
            if full > 0:
                domains.setdefault(name, []).append(float(counter.get("incremental", 0)) / full)
    entries = [(name, statistics.median(v)) for name, v in sorted(domains.items())]
    for i, (name, value) in enumerate(entries):
        yy = 270 + i * 105
        text(draw, (1110, yy), name, 19)
        draw.rounded_rectangle((1110, yy + 34, 2020, yy + 68), 12, fill=THEME["grid"])
        draw.rounded_rectangle(
            (1110, yy + 34, 1110 + max(3, 910 * min(value, 1.0)), yy + 68),
            12,
            fill=THEME["accent"],
        )
        text(draw, (2045, yy + 51), f"{value:.2%}", 18, bold=True, anchor="lm")

    # Baseline pass/work.
    card(canvas, (70, 835, 2130, 1430))
    text(draw, (100, 875), "Baselines — safety pass rate and median work/FULL", 28, bold=True)
    methods = baseline_summary.get("baselines", {})
    order = ["FULL", "CBRC", "EMPIRICAL", "EXACT", "FRACTION", "RADIUS_0", "RADIUS_1", "RADIUS_2", "RADIUS_3"]
    table = [(name, methods[name]) for name in order if name in methods]
    col_w = 2050 // max(len(table), 1)
    for i, (name, item) in enumerate(table):
        x = 90 + i * col_w
        pass_rate = float(item.get("passRate", 0.0))
        ratio = item.get("medianWorkRatioFull")
        ratio = 0.0 if ratio is None else float(ratio)
        color = THEME["certificate"] if name == "CBRC" else THEME["full"]
        text(draw, (x + col_w / 2, 950), name, 17, bold=True, anchor="mm")
        draw.rectangle((x + 35, 1000, x + col_w - 35, 1300), outline=THEME["grid"], width=2)
        h1 = 250 * pass_rate
        draw.rectangle((x + 48, 1285 - h1, x + col_w / 2 - 8, 1285), fill=color)
        h2 = 250 * min(ratio, 1.0)
        draw.rectangle((x + col_w / 2 + 8, 1285 - h2, x + col_w - 48, 1285), fill=THEME["edit"])
        text(draw, (x + col_w / 2, 1345), f"pass {pass_rate:.0%} · work {ratio:.2%}", 14, anchor="mm")

    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, quality=95)


def mosaic(rows: list[dict[str, Any]], campaign_dir: Path, output: Path, maximum=20):
    selected = rows[:maximum]
    cols = 4
    cell_w, cell_h = 520, 330
    rows_n = math.ceil(len(selected) / cols)
    canvas = Image.new("RGB", (cols * cell_w + 100, rows_n * cell_h + 140), THEME["paper"])
    draw = ImageDraw.Draw(canvas)
    text(draw, (50, 48), "Frozen public revision matrix", 40, bold=True)
    for index, row in enumerate(selected):
        c = index % cols
        r = index // cols
        x = 50 + c * cell_w
        y = 110 + r * cell_h
        visuals = case_visuals(campaign_dir, str(row["case_id"]))
        image = fit(visuals["after"], 470, 230)
        canvas.paste(image, (x, y))
        state = "FULL" if row.get("fallback_full", False) else "LOCAL"
        color = THEME["fallback"] if state == "FULL" else THEME["local"]
        badge(draw, (x + 335, y + 12, x + 455, y + 48), state, color)
        text(draw, (x, y + 246), case_label(row), 16, bold=True)
        text(draw, (x, y + 274), f"work/FULL {work_ratio(row):.2%}", 15, THEME["muted"])
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, quality=95)


def overview_svg(output: Path):
    output.parent.mkdir(parents=True, exist_ok=True)
    svg = """<svg xmlns="http://www.w3.org/2000/svg" width="1800" height="900" viewBox="0 0 1800 900">
<rect width="1800" height="900" rx="30" fill="#F7F8FA"/>
<style>
.t{font:700 38px sans-serif;fill:#10131A}.h{font:700 24px sans-serif;fill:#10131A}
.b{font:18px sans-serif;fill:#475467}.s{font:700 18px sans-serif;fill:white}
.box{fill:white;stroke:#D8DEE9;stroke-width:3}.arrow{stroke:#667085;stroke-width:5;fill:none;marker-end:url(#m)}
</style>
<defs><marker id="m" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#667085"/></marker></defs>
<text x="70" y="75" class="t">MAVEB / CBRC — certified revision pipeline</text>
<rect x="70" y="160" width="260" height="150" rx="22" class="box"/><text x="100" y="205" class="h">Persistent world</text><text x="100" y="245" class="b">real RGB / trained 3DGS</text><text x="100" y="275" class="b">stable entity ownership</text>
<path d="M330 235H430" class="arrow"/>
<rect x="430" y="160" width="250" height="150" rx="22" class="box"/><text x="460" y="205" class="h">Revision</text><text x="460" y="245" class="b">local authored edit</text><text x="460" y="275" class="b">dirty support</text>
<path d="M680 235H780" class="arrow"/>
<rect x="780" y="140" width="330" height="190" rx="22" class="box"/><text x="815" y="190" class="h">CBRC certificate</text><text x="815" y="230" class="b">exact HARD closure</text><text x="815" y="260" class="b">analytic finite-change bounds</text><text x="815" y="290" class="b">QoI-specific proof</text>
<path d="M1110 235H1210" class="arrow"/>
<rect x="1210" y="100" width="500" height="270" rx="22" class="box"/><text x="1245" y="150" class="h">Decision</text>
<rect x="1260" y="200" width="185" height="70" rx="18" fill="#28C76F"/><text x="1352" y="243" text-anchor="middle" class="s">LOCAL REPAIR</text>
<rect x="1480" y="200" width="185" height="70" rx="18" fill="#F04438"/><text x="1572" y="243" text-anchor="middle" class="s">FULL FALLBACK</text>
<text x="1260" y="315" class="b">safe → touch only certified support</text><text x="1480" y="345" class="b">unsafe/unstable → refuse locality</text>
<path d="M945 330V475" class="arrow"/>
<rect x="600" y="475" width="690" height="270" rx="28" class="box"/><text x="645" y="530" class="h">Independent evidence</text>
<text x="645" y="575" class="b">FULL-after reference replay · actual residual · certified bound · ε</text>
<text x="645" y="615" class="b">work ledger · hardware calibration · baseline/ablation suite · parity</text>
<rect x="645" y="660" width="600" height="46" rx="16" fill="#18C6D9"/><text x="945" y="691" text-anchor="middle" class="s">actual ≤ bound ≤ ε — or the case is rejected</text>
</svg>"""
    output.write_text(svg)


def caption_frame(base: Image.Image, title_value: str, subtitle: str, badge_value: str | None = None, badge_color=None):
    canvas = Image.new("RGB", (1280, 720), THEME["paper"])
    canvas.paste(fit(base, 1280, 600), (0, 120))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 1280, 120), fill=THEME["ink"])
    text(draw, (42, 34), title_value, 32, THEME["white"], bold=True)
    text(draw, (42, 78), subtitle, 18, (205, 211, 220))
    if badge_value:
        badge(draw, (1000, 34, 1238, 88), badge_value, badge_color or THEME["accent"])
    return canvas


def animated_assets(rows: list[dict[str, Any]], campaign_dir: Path, teaser: Path, supplement: Path, local_case: str, fallback_case: str):
    by_id = {str(row["case_id"]): row for row in rows}
    local = by_id[local_case]
    fallback = by_id[fallback_case]
    local_v = case_visuals(campaign_dir, local_case)
    fallback_v = case_visuals(campaign_dir, fallback_case)

    ratio = work_ratio(local)
    sequence = [
        (local_v["before"], "A persistent world changes", "Real public RGB-derived scene", None, None, 8),
        (local_v["effect"], "The edit can be visually large", "Raw before → after effect", "EDIT", THEME["edit"], 10),
        (local_v["support"], "CBRC certifies the affected support", "Analytic bound, not a heuristic mask", "CERTIFIED", THEME["certificate"], 12),
        (local_v["repair"], "Repair only the certified region", f"selected output work = {ratio:.2%} of FULL", "LOCAL", THEME["local"], 14),
        (local_v["after"], "Matches the FULL-after reference", f"measured residual = {local['qois']['rgb_linf']['measured_full_reference_error']:.2e}", "SAFE", THEME["local"], 12),
        (fallback_v["support"], "But locality is not always safe", case_label(fallback), "HIGH COUPLING", THEME["fallback"], 10),
        (fallback_v["after"], "MAVEB refuses to bluff", "unstable / unsafe support → automatic FULL repair", "FULL FALLBACK", THEME["fallback"], 16),
    ]
    frames = []
    durations = []
    for image, title_value, subtitle, badge_value, badge_color, repeat in sequence:
        frame = caption_frame(image, title_value, subtitle, badge_value, badge_color)
        for _ in range(repeat):
            frames.append(frame.copy())
            durations.append(83)
    teaser.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        teaser,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=False,
    )

    # Supplement: one compact card per frozen case.
    supplemental = []
    for row in rows:
        vis = case_visuals(campaign_dir, str(row["case_id"]))
        state = "FULL FALLBACK" if row.get("fallback_full", False) else "LOCAL"
        color = THEME["fallback"] if row.get("fallback_full", False) else THEME["local"]
        frame = caption_frame(
            vis["after"],
            case_label(row),
            f"work/FULL {work_ratio(row):.2%} · Δ {row.get('changed_fraction',0):.2%}",
            state,
            color,
        )
        supplemental.extend([frame] * 3)
    supplement.parent.mkdir(parents=True, exist_ok=True)
    supplemental[0].save(
        supplement,
        save_all=True,
        append_images=supplemental[1:],
        duration=100,
        loop=0,
        optimize=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-mosaic-cases", type=int, default=20)
    args = parser.parse_args()

    campaign = args.campaign_dir.resolve()
    output = args.output_dir.resolve()
    rows = load_rows(campaign / "campaign-rows.jsonl")
    baselines = load_json(campaign / "baseline-summary.json")
    if not rows:
        raise ValueError("visualization requires campaign rows")

    hero_cases = hero(rows, campaign, output / "figures" / "F0_hero.png")
    chart_sheet(rows, baselines, output / "figures" / "F9_evidence_dashboard.png")
    mosaic(rows, campaign, output / "figures" / "F10_case_mosaic.png", args.max_mosaic_cases)
    overview_svg(output / "figures" / "F0_system_overview.svg")
    animated_assets(
        rows,
        campaign,
        output / "video" / "MAVEB_teaser.gif",
        output / "video" / "MAVEB_supplementary_cases.gif",
        hero_cases["local"],
        hero_cases["fallback"],
    )

    manifest = {
        "schemaVersion": 1,
        "artifact": "maveb-siggraph-visual-package",
        "sourceCampaign": str(campaign),
        "rows": len(rows),
        "heroCases": hero_cases,
        "assets": {
            "hero": "figures/F0_hero.png",
            "overview": "figures/F0_system_overview.svg",
            "dashboard": "figures/F9_evidence_dashboard.png",
            "mosaic": "figures/F10_case_mosaic.png",
            "teaser": "video/MAVEB_teaser.gif",
            "supplement": "video/MAVEB_supplementary_cases.gif",
        },
        "scientificRule": (
            "Every scene frame comes from the independent full-reference oracle; "
            "all badges and numeric overlays are derived from campaign evidence."
        ),
    }
    (output / "VISUAL_PACKAGE.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
