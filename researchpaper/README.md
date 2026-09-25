# MAVEB Research Paper

Title: **Repair What Matters: Criticality-Bounded Revision Cones for Persistent Captured Worlds**

This folder is the editable manuscript package for the current CBRC v1 paper line. The scientific source is `main.tex`; generated PDF/DOCX artifacts are release outputs and must be regenerated whenever the manuscript source changes.

## Current scientific state

The paper contains two deliberately separate evidence lines.

- **Broad systems campaign:** 1,275 revisions over 85 scenes spanning 3RScan, ARKitScenes, Bonn RGB-D Dynamic, and 13 pinned trained GraphDECO 3DGS scenes. CBRC selects 935 LOCAL repairs and 340 FULL fallbacks, with zero observed certificate violations and median calibrated selected work/FULL of 0.47447 (bootstrap 95% CI 0.46657–0.47885).
- **Residual-sensitive sequence:** v4 is an immutable negative diagnostic, v5 isolates the opacity-delta certificate with translation as a control, and v6 repeats the unchanged mechanism across 20 scenes (five per dataset family). The v6 scene-level opacity-minus-translation difference is 0.477 with dataset-stratified bootstrap 95% CI [0.432, 0.517]. The accepted residuals remain far from the tolerance boundary, so certificate conservatism is retained as a measured limitation.

The manuscript does not turn calibrated work into a wall-clock speedup claim, does not claim universal safety or global optimality, and distinguishes revision fidelity within an evaluated representation from source-photograph reconstruction quality.

## Files

- `main.tex`: authoritative ACM/TOG-style manuscript source.
- `references.bib`: bibliography used by the manuscript.
- `figures/system_flow.tex`: editable vector system architecture used as Figure 1.
- `figures/figure2_exact.png`: exact author-supplied Figure 2, byte-for-byte unchanged.
- `figures/local_revision_poster.tex` and `figures/qualitative_frozen.png`: retained historical assets; they are not figures in the current `main.tex`.
- `supplement.tex` and `supplement_gaussian_bound.tex`: supplement sources.
- `build_manuscript.py`: reproducible manuscript builder and structural QA gate.
- `MANUSCRIPT_QA.md`: release and layout requirements.
- `FINAL_MANUSCRIPT_AUDIT_2026-09-25.md`: current claim/citation/evidence/release audit.
- `REVIEW_RESPONSE_2026-09-21.md`: external-feedback response ledger, updated through the final v6 integration.
- `CLAIM_METHOD_CITATION_AUDIT_2026-09-22.md`: historical pre-v6 audit, retained for traceability.
- `MAVEB_manuscript.pdf`, `MAVEB_manuscript.docx`, `MAVEB_supplement.pdf`, and `MAVEB_manuscript_package.zip`: generated release artifacts.

## Anonymous review

For SIGGRAPH/SIGGRAPH Asia review, switch the class declaration in `main.tex` to:

```latex
\documentclass[acmtog,anonymous,review]{acmart}
\acmSubmissionID{paperID}
```

The checked-in author-visible version contains the author name and email. Venue submission copies must use the target venue's required anonymity mode and metadata.

## Exact Figure 2 and layout

Figure 2 is preserved byte-for-byte; LaTeX only scales its placement.

- Dimensions: 1487 × 1058, RGBA PNG
- Size: 2,499,137 bytes
- SHA-256: `e8cfa3b68930c9052c7fbe4190eb7841efb428ab1bfe587e03dbea9fac0d1f24`

Its embedded micro-metrics are illustrative. The caption separates them from the 1,275-case headline and explicitly rules out reading them as a wall-clock speedup or universal correctness claim.

## Historical validation assets

Earlier public-pilot runs using Tanks & Temples / Deep Blending and the five-case trained-3DGS check remain in repository history and evidence files. They were useful development-stage validation, but they are **not** the current manuscript's breadth headline and must not replace the 1,275-case/85-scene campaign or the v4→v5→v6 residual-sensitive sequence when describing the paper.

## Build and CI

Canonical local build:

```bash
python3 researchpaper/build_manuscript.py --build-dir /tmp/maveb-manuscript-build
```

The manuscript workflow runs the same builder for manuscript branches and pull requests. It verifies the exact Figure 2 hash, compiles the ACM PDF and supplement, exports the editable DOCX, validates figure/table/equation structure, records SHA-256 checksums, packages the sources and outputs, and uploads the generated release bundle.

The PDF is the authoritative two-column author manuscript. The DOCX is an editable convenience export; it preserves the two manuscript figures, six content tables, eighteen editable displayed equations, and the exact Figure 2 media bytes.

A release is considered synchronized only when the generated PDF, DOCX, supplement, package, and checksum manifest were produced from the same current source state and pass the gates in `MANUSCRIPT_QA.md`.

See `FINAL_MANUSCRIPT_AUDIT_2026-09-25.md` for the current scientific and release audit.
