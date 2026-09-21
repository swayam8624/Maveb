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
