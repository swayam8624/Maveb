# CBRC paper claim ledger — 2026-09-24

> **2026-09-25 status note.** The broad 1,275-case campaign values in this ledger remain current. The “Reviewer-v2 boundary” section below records the pre-confirmation state from 2026-09-24 and has been superseded by the completed v4→v5→v6 residual-sensitive evidence integrated into `researchpaper/main.tex` and `researchpaper/FINAL_MANUSCRIPT_AUDIT_2026-09-25.md`. Do not use the older conditional prohibition to describe the final manuscript.

This ledger supersedes the 2026-09-21 headline ledger for the current manuscript. Historical evidence remains preserved in the older files.

## Supported by the completed paper-grade campaign

- The frozen campaign contains **1,275 revisions over 85 scenes**.
- It spans **3RScan, ARKitScenes, Bonn RGB-D Dynamic, and 13 trained GraphDECO 3DGS scenes**.
- It spans **translation, rotation, uniform-scale, and opacity** edits.
- CBRC selects **935 certified LOCAL repairs** and **340 automatic FULL fallbacks**.
- The observed LOCAL rate is **73.33%**, Wilson 95% CI **70.84–75.69%**.
- The frozen campaign observes **0 certificate violations**.
- Median calibrated selected work is **0.47447 of FULL**, bootstrap 95% CI **0.46657–0.47885**.
- The median calibrated-work reduction relative to FULL is **52.55%**.
- All **1,275 / 1,275** selected renders are byte-identical to independent FULL-after on the audited benchmark views.
- Against FULL, CBRC has lower calibrated work in **935** jointly certified cases and ties in **340**; exact two-sided sign-test p = **6.89e-282**.
- Locality decreases with frozen coupling severity:
  - low: 340/340 LOCAL;
  - medium: 340/340 LOCAL;
  - high: 170 LOCAL / 85 FULL;
  - adversarial: 85 LOCAL / 255 FULL.

## Supported by edit-family evidence

- Opacity: **255 LOCAL / 0 FULL**.
- Rotation: **255 LOCAL / 85 FULL**.
- Translation: **255 LOCAL / 85 FULL**.
- Uniform scale: **170 LOCAL / 170 FULL**.
- Each edit family has **0 observed certificate violations**.

## Supported, but only with qualification

- **“Median selected calibrated work is 0.474 of FULL”** is supported.
- **“52.55% lower calibrated work at the median”** is supported.
- **“~2.108x lower calibrated work”** is arithmetically equivalent, but percentage reduction is preferred for clarity.
- **“Speedup”** is unsupported without matched end-to-end timing.
- **“No certificate violations were observed in 1,275 frozen cases”** is supported.
- **“CBRC cannot violate tolerance”** is unsupported.
- **“Selected output exactly matches FULL-after on the audited views”** is supported.
- **“The representation is photorealistically accurate to the source photographs”** is a different claim and is unsupported by this audit.
- The identical 73.33% LOCAL rate across the four dataset groups follows from the common frozen case template; it is not evidence that all datasets behave identically.

## Neutral/negative evidence that must remain visible

- EMPIRICAL ordering followed by analytic re-certification ties CBRC on all 1,275 jointly certified cases in the reported work comparison.
- Several structural/analytic ablations are aggregate ties on this frozen real matrix.
- The global-norm-tail ablation remains certified but loses locality: CBRC is lower-work in 935 cases and ties 340.
- Exact-only and fixed-radius comparison policies certify only 340/1,275 cases.
- Changed-fraction selection certifies 537/1,275.
- Removing certified fallback leaves only 340 certified cases.

## Reviewer-v2 boundary

The broad campaign does **not** establish useful approximate LOCAL repair with a non-zero residual because selected-to-FULL error is zero throughout the audited broad matrix.

A separate reviewer-v2 protocol is implemented and frozen to test:

`0 < actual <= certified bound <= epsilon`

under deterministic partial repair.

Until its frozen audit reports `reviewerEvidenceReady=true`, the manuscript must not claim:
- certified non-zero LOCAL residuals on real scenes;
- tolerance crossovers on the reviewer-v2 protocol;
- cross-dataset non-zero residual evidence.

The manuscript bridge enforces this rule automatically.

## Remaining measured limitations

- Calibrated work is not paired wall-clock runtime.
- The broad performance path remains output-side: Gaussian inspection/update, GPU publication, and temporal invalidation dominate measured work.
- Dataset-native worlds use deterministic seeded Gaussian representations; the 13 GraphDECO scenes provide the trained-3DGS representation group.
- Selected-to-FULL raster fidelity is not source-photograph reconstruction fidelity.
- The planner is conservative and does not claim global combinatorial minimum work.
- Unsupported analytic cycles fail closed.

## Prohibited claims

Do not claim:
- universal safety;
- wall-clock speedup;
- global optimality;
- semantic ownership where ownership is only deterministic/spatial;
- that every ablation matters empirically on every scene;
- that reviewer-v2 succeeded before its frozen audit passes;
- any venue acceptance guarantee.

## Traceability

Current headline values must trace to:
- `build/broad-benchmark-paper/BROAD_CAMPAIGN_COMPLETE.json`;
- `build/broad-benchmark-paper/campaign/campaign-rows.jsonl`;
- `build/broad-benchmark-paper/visual-quality/CBRC_VISUAL_QUALITY.json`;
- `build/broad-benchmark-paper/statistics/CROSS_DATASET_STATISTICS.json`;
- evidence Git SHA `d61ef9ea7575def9d7d50f83c1a9a4da0761b950`.

The repository summary is `CBRC_PAPER_GRADE_EVIDENCE_2026-09-24.json`.
