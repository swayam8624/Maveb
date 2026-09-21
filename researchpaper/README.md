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

## Build and CI

The canonical local build is:

```bash
python3 researchpaper/build_manuscript.py --build-dir /tmp/maveb-manuscript-build
```

The GitHub manuscript workflow uses the same builder. It runs for manuscript changes on `main`, on `manuscript/**` branches, and on pull requests targeting `main`. It verifies the exact Figure 2 SHA-256 before compiling. On `manuscript/**` push events it may commit regenerated PDF/DOCX/supplement/package artifacts back to the manuscript branch; on protected `main` it validates without attempting to push generated files.

The PDF is the authoritative two-column ACM author manuscript. The DOCX is an editable single-column export; it is not an ACM typesetting substitute. Artifact completion does not imply venue acceptance or any publication-tier outcome.

See `MANUSCRIPT_QA.md` for the exact verification gates and scope.
