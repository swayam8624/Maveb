# MAVEB manuscript media index

This file maps committed media to paper and supplementary roles.

Root:

research/results/visualizations/

# Primary paper media

| ID | Path | Recommended role |
|---|---|---|
| F0 | research/results/visualizations/public/F0_hero.png | teaser |
| Overview | research/results/visualizations/public/F0_system_overview.svg | method overview |
| F1 | research/results/visualizations/paper/F1_actual_vs_bound.svg | certificate validity |
| F2 | research/results/visualizations/paper/F2_work_vs_changed_fraction.svg | work scaling |
| F3 | research/results/visualizations/paper/F3_coupling_cone.svg | cone response |
| F4 | research/results/visualizations/paper/F4_fallback_crossover.svg | local/FULL crossover |
| F5 | research/results/visualizations/paper/F5_effectivity.svg | certificate effectivity |
| F6 | research/results/visualizations/paper/F6_layer_work.svg | layer work |
| F7 | research/results/visualizations/paper/F7_cone_support_residual.svg | support and residual |
| F8 | research/results/visualizations/paper/F8_adversarial_fallback.svg | fail-closed examples |
| F9 | research/results/visualizations/public/F9_evidence_dashboard.png | evidence dashboard |
| F10 | research/results/visualizations/public/F10_case_mosaic.png | frozen-case coverage |
| F11 | research/results/visualizations/sparse/F11_sparse_discovery.svg | sparse discovery scaling |
| F12 | research/results/visualizations/representation/F12_representation_comparison.svg | representation validation |

# Post-reviewer practical-evidence media

These assets are generated only after running the separate frozen reviewer-stress v2 campaign. The v2 selected repair is a rendered hybrid Gaussian state with a predeclared deterministic omitted subset and an independent residual certificate. They must not be cited as established results before the corresponding audit exists.

| Asset | Generated path | Role |
|---|---|---|
| reviewer real-scene panel | build/reviewer-stress-v2/visuals/F_REVIEWER_REAL_SCENE_LOCAL_VS_FULL.png | captured RGB context + LOCAL/FULL/residual/support evidence |
| tolerance crossover | build/reviewer-stress-v2/visuals/F_REVIEWER_TOLERANCE_CROSSOVER.png | identical edit across fixed epsilon ladder |
| reviewer evidence audit | build/reviewer-stress-v2/analysis/REVIEWER_EVIDENCE_AUDIT.json | machine-readable non-zero/crossover/readiness evidence |
| reviewer visual provenance | build/reviewer-stress-v2/visuals/REVIEWER_VISUALS.json | source-RGB and figure provenance |

The paper should promote these into numbered figures only after the frozen run produces the claimed phenomenon. An OPEN readiness gate is reported as a limitation rather than hidden by cherry-picking.

# Trained-3DGS visual set

| Asset | Path |
|---|---|
| hero | research/results/visualizations/trained-3dgs/F0_trained_3dgs_hero.png |
| system overview | research/results/visualizations/trained-3dgs/F0_system_overview.svg |
| evidence dashboard | research/results/visualizations/trained-3dgs/F9_trained_3dgs_evidence_dashboard.png |
| case mosaic | research/results/visualizations/trained-3dgs/F10_trained_3dgs_case_mosaic.png |
| teaser GIF | research/results/visualizations/trained-3dgs/MAVEB_teaser.gif |
| supplementary GIF | research/results/visualizations/trained-3dgs/MAVEB_supplementary_cases.gif |

# Public animated media

| Asset | Path |
|---|---|
| teaser GIF | research/results/visualizations/public/MAVEB_teaser.gif |
| supplementary cases GIF | research/results/visualizations/public/MAVEB_supplementary_cases.gif |

# Generation sources

SIGGRAPH visual generator:

research/visualization/cbrc_siggraph_visuals.py

Representation-comparison generator:

research/visualization/cbrc_representation_comparison.py

Storyboard:

research/visualization/SIGGRAPH_VISUAL_STORYBOARD.md

Style:

research/visualization/style.json

# Media rules

1. Do not modify scientific geometry, masks, residuals, certificate values, or local/FULL decisions for aesthetics.
2. Regenerate figures from frozen evidence rather than editing numbers manually.
3. Use vector SVG where possible for plots.
4. Use raster PNG for scene composites when necessary.
5. Convert GIF-based motion to the target venue's preferred video format for final supplementary submission.
6. Anonymize all review-stage media.
7. Record third-party dataset/model attribution for scene-bearing media.

## Paper-grade 2026-09-24 evidence

Primary broad-campaign artifacts are now generated from the completed 1,275-case / 85-scene freeze:

- `build/broad-benchmark-paper/BROAD_CAMPAIGN_COMPLETE.json`
- `build/broad-benchmark-paper/visual-quality/CBRC_VISUAL_QUALITY.json`
- `build/broad-benchmark-paper/statistics/CROSS_DATASET_STATISTICS.json`

These supersede the old 60-case public and five-case trained-representation headline evidence for manuscript claims.

## Reviewer-v2 manuscript bridge

After `bash run_reviewer_stress_campaign.sh`, the fail-closed bridge writes:

- `researchpaper/generated/reviewer_v2_status.md` — always records PASS/OPEN readiness gates.
- `researchpaper/generated/reviewer_v2_results.tex` — contains manuscript claim text only when `reviewerEvidenceReady=true`; otherwise it contains comments only.
- `researchpaper/figures/reviewer_v2_real_scene.png` — copied only from a ready frozen visual package.
- `researchpaper/figures/reviewer_v2_crossover.png` — copied only when a frozen tolerance crossover figure exists and all readiness gates pass.

`researchpaper/main.tex` conditionally includes the generated reviewer-v2 block. This prevents an OPEN reviewer experiment from silently becoming a manuscript claim.
