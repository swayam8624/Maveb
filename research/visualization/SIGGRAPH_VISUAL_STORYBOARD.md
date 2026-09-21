# MAVEB SIGGRAPH Visual Storyboard

This document is an implementation contract for the paper figures and videos.
Every visual must be generated from frozen evidence or independent oracle frames.
No beauty edit may change geometry, support masks, residuals, bounds, work, or the
local/FULL decision.

## Hero figure

Six aligned panels for one certified local case:

1. Before persistent world.
2. Intended edit effect.
3. Certified support.
4. Selected local repair.
5. FULL-after reference.
6. Post-repair residual.

A second row shows one adversarial/high-coupling case ending in FULL fallback.
The figure must visibly communicate the core claim without relying on the caption:
**local when proven safe, FULL when not**.

## System overview

Left-to-right flow:

Persistent real world -> revision -> CBRC certificate -> branch:
- LOCAL repair when bound <= epsilon.
- FULL fallback when locality is unsafe or temporal validation is unstable.

A lower evidence rail shows:
FULL-after replay -> actual residual -> certified bound -> work ledger ->
hardware calibration -> baselines/ablations -> paper artifacts.

The invariant `actual <= bound <= epsilon` is the visual anchor.

## Paper figure set

- F0 hero: before/edit/support/repair/FULL/residual + fallback row.
- F1 safety scatter: measured post-repair residual vs certified bound with y=x.
- F2 changed fraction vs selected work/FULL.
- F3 coupling regime vs repair-cone fraction.
- F4 local-to-FULL crossover curve.
- F5 certificate effectivity distribution.
- F6 per-domain work ledger and hardware-calibrated estimate.
- F7 screen-space certificate support vs actual edit/residual.
- F8 adversarial/high-coupling fallback examples.
- F9 evidence dashboard: safety, work decomposition, baseline comparison.
- F10 frozen campaign mosaic: many scenes/cases with LOCAL/FULL badges.
- F11 indexed candidate discovery scaling: scan vs index inspections and latency.
- F12 trained-3DGS vs SfM-seeded representation comparison.

## 18-second teaser

0–2 s — persistent real scene, slow push-in.
2–4 s — edit-effect heatmap blooms from the edited region.
4–7 s — certified support reveals in electric cyan.
7–10 s — selected repair replaces only certified support; work counter drops.
10–12 s — FULL-after appears beside selected repair; residual map stays dark.
12–15 s — adversarial case; support expands / temporal validation becomes unsafe.
15–18 s — automatic FULL fallback, then title card:
“MAVEB / CBRC — Repair only what you can prove.”

Motion rule: no decorative animation that does not explain a scientific state change.

## 2–4 minute paper video

1. Motivation: persistent captured worlds change repeatedly.
2. Why FULL is wasteful and heuristic locality is unsafe.
3. Persistent entity/Gaussian state and revision graph.
4. Exact HARD closure + analytic finite-change bounds.
5. Live local case: edit -> support -> selected repair -> FULL comparison.
6. Independent oracle: actual vs bound.
7. Large public campaign: scene/case mosaic and safety scatter.
8. Hardware-calibrated work + actual timing decomposition.
9. Baselines and ablations.
10. High-coupling fallback.
11. Trained 3DGS validation.
12. Limitations and final message.

## Supplementary video

The supplement must include every frozen campaign-v2 case in deterministic order.
For each case show:
- scene / revision ID,
- coupling regime,
- before,
- FULL-after,
- support,
- selected output,
- residual,
- local/FULL decision,
- native and calibrated work ratios,
- raw edit effect,
- certified bound and epsilon.

No failed case is removed from the supplement.

## Art direction

Semantic palette:
- intended edit: warm orange,
- certified support: electric cyan,
- certified local repair: green,
- FULL fallback: red,
- FULL reference: slate,
- residual: red/yellow heat,
- base scene/UI: near-black on warm white.

Camera motion is restrained and scientific. Typography is clean sans with tabular
numbers. Captions state measured quantities and never convert a work-domain ratio
into a wall-clock speedup unless the hardware-calibrated and measured timing
experiments support that wording.
