# MAVEB Manuscript QA

This file records the reproducible manuscript build gates for the final CBRC v1 paper line.

## Canonical build

Run from the repository root:

```bash
python3 researchpaper/build_manuscript.py --build-dir /tmp/maveb-manuscript-build
```

The builder compiles the ACM author manuscript, compiles the supplement, exports the editable DOCX, and performs structural checks.

## Required gates

1. `researchpaper/figures/figure2_exact.png` must exist and have SHA-256:
   `e8cfa3b68930c9052c7fbe4190eb7841efb428ab1bfe587e03dbea9fac0d1f24`.
2. LaTeX compilation must complete without overfull h/v boxes, undefined references, multiply-defined references, or missing-character warnings.
3. The manuscript PDF and supplement PDF must compile from the committed sources.
4. The DOCX export must contain all three manuscript figures and all six editable content tables.
5. The DOCX must contain the expected 16 editable displayed equations with stable plain-Word numbering and must not contain unconverted `$$` TeX blocks.
6. The exact Figure 2 bytes must be embedded in the DOCX media package.
7. Generated artifacts are packaged together with the manuscript sources and figure assets.
8. Release QA includes rendered visual inspection of every manuscript PDF page, every DOCX page, and every supplement PDF page.

## Scope

These checks validate manuscript reproducibility, structural consistency, exact Figure 2 provenance, and layout-related failure conditions enforced by the builder. They do not change frozen scientific evidence, do not establish wall-clock speedup, and do not imply venue acceptance.

The authoritative venue layout is the compiled ACM PDF. The DOCX is an editable convenience export and should not be treated as the publication typesetting reference.
