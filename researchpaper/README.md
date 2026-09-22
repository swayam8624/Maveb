# MAVEB Research Paper

Title: **Repair What Matters: Criticality-Bounded Revision Cones for Persistent Captured Worlds**

This folder is the editable manuscript package for the current CBRC v1 paper line.

## Files

- `main.tex`: Overleaf-ready ACM/TOG-style manuscript source.
- `references.bib`: bibliography.
- `figures/system_flow.tex`: editable vector system architecture.
- `figures/figure2_exact.png`: exact author-supplied Figure 2, byte-for-byte unchanged.
- `figures/local_revision_poster.tex`: historical reconstruction, unused by this manuscript.
- `figures/qualitative_frozen.png`: frozen qualitative result panel used by the manuscript.
- `MAVEB_manuscript.pdf`: compiled author-visible manuscript, rebuilt from the current source.
- `MAVEB_manuscript.docx`: editable Word export, rebuilt from the current source.
- `MAVEB_supplement.pdf`: compiled supplement.
- `MAVEB_manuscript_package.zip`: generated manuscript package.
- `build_manuscript.py`: reproducible manuscript builder and structural QA gate.
- `MANUSCRIPT_QA.md`: manuscript build/verification record and commands.

The manuscript reuses frozen result imagery from `research/results/visualizations/`.

## Anonymous review

For SIGGRAPH/SIGGRAPH Asia review, switch the class declaration in `main.tex` to:

```latex
\documentclass[acmtog,anonymous,review]{acmart}
\acmSubmissionID{paperID}
```

The visible author version contains Swayam Singal and the requested email address only.

## Claim discipline

The manuscript distinguishes calibrated/native work reduction from wall-clock speedup, reports zero observed violations only within the frozen evaluation domain, describes the greedy cone as certified-feasible rather than globally optimal, and keeps the near-global Gaussian discovery bottleneck explicit.

## Review-driven revision

The current manuscript incorporates the 2026-09-21 review pass: quantitative baseline and ablation tables, explicit revision criticality, a formalized Gaussian finite-edit proposition, stronger incremental/error-control related work, exact Figure 2 usage, bounded table layouts, and clean author-visible formatting.

See `REVIEW_RESPONSE_2026-09-21.md` for the revision ledger and `supplement_gaussian_bound.tex` for the extended Proposition 1 derivation.

## Exact Figure 2 and layout

Figure 2 uses the original author-supplied PNG bytes without cropping, redrawing, resampling, recompression, or optimization. LaTeX scales its placement uniformly on the page, preserving the image and its aspect ratio.

- Dimensions: 1487 x 1058, RGBA PNG
- Size: 2,499,137 bytes
- SHA-256: `e8cfa3b68930c9052c7fbe4190eb7841efb428ab1bfe587e03dbea9fac0d1f24`

The image's embedded micro-metrics are illustrative. Its caption distinguishes them from the frozen 60-case headline and qualifies its correctness language by the stated assumptions. All six tables use bounded widths; Table 3's note wraps below the table. Numerical columns remain aligned and text columns wrap.

## Graphics benchmark and visual-fidelity audit

The submission-facing graphics audit now makes two requirements explicit:

- the public matrix uses named benchmark inputs from **Tanks & Temples** (Train, Truck) and **Deep Blending** (Dr Johnson, Playroom), with the source archive pinned by size/SHA-256;
- `research/analysis/cbrc_visual_quality.py` compares each final selected benchmark-view render with the independently rendered FULL-after reference and emits JSON, CSV, and `F13_benchmark_visual_quality.png`.

The audit reports byte-domain MAE/RMSE/max error, exact-pixel fraction, PSNR semantics, and before-to-FULL changed-pixel fraction. FULL fallback cases are scored using the actual selected FULL execution; the rejected local candidate is retained separately. These metrics establish **repair fidelity to FULL for the evaluated representation**, not photorealistic reconstruction quality against the original source photographs.

In the verified 60-case public rerun, all **44/44 LOCAL** selected renders were byte-identical to the independent FULL-after render at 8-bit RGB precision; the remaining 16 cases correctly selected FULL. Before-to-FULL edits changed a median **1.74%** of pixels across all frozen views (range **0--7.88%**), with at least one changed pixel in **57/60** views. Dataset medians were **1.89%** for Deep Blending and **1.71%** for Tanks & Temples. The visual-quality rerun is used only for these image-space metrics and does **not** replace the canonical frozen work-calibration headline (0.36953 work/FULL, 2.706x lower calibrated work).

The same audit runs on the pinned trained-3DGS validation. In the verified five-case run, all four LOCAL selected renders were byte-identical to FULL-after; the fifth case selected FULL. The before-to-FULL edits changed 1.60--2.66% of pixels across those frozen views (median 2.23%).

## Build and CI

The canonical local build is:

```bash
python3 researchpaper/build_manuscript.py --build-dir /tmp/maveb-manuscript-build
```

The GitHub manuscript workflow uses the same builder. It runs for manuscript changes on `main`, on `manuscript/**` branches, and on pull requests targeting `main`. It verifies the exact Figure 2 SHA-256 before compiling, then validates and uploads the PDF, editable DOCX, supplement, and package as workflow artifacts. CI does not rewrite repository files or push generated commits.

The PDF is the authoritative two-column ACM author manuscript. The DOCX is an editable single-column export; it preserves the manuscript figures, six content tables, sixteen editable equations with stable Word-side numbering, and the exact Figure 2 media bytes. It is not an ACM typesetting substitute. Artifact completion does not imply venue acceptance or any publication-tier outcome.

See `MANUSCRIPT_QA.md` for the exact verification gates and scope.
