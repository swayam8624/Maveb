# MAVEB / CBRC paper-grade evidence summary — 2026-09-24

This file is a repository-level summary of the completed broad campaign. The authoritative run artifacts remain the local frozen files under `build/broad-benchmark-paper/` generated at evidence Git SHA `d61ef9ea7575def9d7d50f83c1a9a4da0761b950`.

## Headline result

- 1,275 revisions over 85 scenes and four dataset/representation groups.
- 935 certified LOCAL repairs and 340 FULL fallbacks.
- 0 observed certificate violations.
- LOCAL rate 73.33%, Wilson 95% CI 70.84–75.69%.
- Median calibrated work/FULL 0.47447, bootstrap 95% CI 0.46657–0.47885.
- 1,275 / 1,275 selected renders are exact to independent FULL-after on the audited views.
- Against FULL, CBRC uses lower calibrated work in 935 jointly certified cases and ties in 340; exact sign-test p = 6.89e-282.

## Dataset coverage

| Dataset / representation | Scenes | Cases | LOCAL | FULL | Median work/FULL |
|---|---:|---:|---:|---:|---:|
| 3RScan | 40 | 600 | 440 | 160 | 0.34063 |
| ARKitScenes | 20 | 300 | 220 | 80 | 0.48322 |
| Bonn RGB-D Dynamic | 12 | 180 | 132 | 48 | 0.47548 |
| Trained GraphDECO 3DGS | 13 | 195 | 143 | 52 | 0.51911 |

## Edit-family coverage

| Edit | Cases | LOCAL | FULL | Median work/FULL |
|---|---:|---:|---:|---:|
| Opacity | 255 | 255 | 0 | 0.45749 |
| Rotation | 340 | 255 | 85 | 0.45257 |
| Translation | 340 | 255 | 85 | 0.47471 |
| Uniform scale | 340 | 170 | 170 | 0.77045 |

## Coupling envelope

- Low: 340 LOCAL / 0 FULL.
- Medium: 340 LOCAL / 0 FULL.
- High: 170 LOCAL / 85 FULL.
- Adversarial: 85 LOCAL / 255 FULL.

## Claim boundary

The 0.47447 value is calibrated work, not wall-clock speedup. Selected-to-FULL equality is revision fidelity within the evaluated representation, not source-photograph reconstruction fidelity. Because all broad selected residuals are zero at the audited precision, this campaign does not establish certificate tightness for an acceptable non-zero residual. Reviewer-v2 is the separate frozen experiment for that question.

## Authoritative local artifacts

- `build/broad-benchmark-paper/BROAD_CAMPAIGN_COMPLETE.json`
- `build/broad-benchmark-paper/campaign/campaign-rows.jsonl`
- `build/broad-benchmark-paper/visual-quality/CBRC_VISUAL_QUALITY.json`
- `build/broad-benchmark-paper/statistics/CROSS_DATASET_STATISTICS.json`
