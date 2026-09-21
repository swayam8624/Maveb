# Manuscript revision response — 2026-09-21

This revision responds to the external manuscript review supplied after the
first complete nine-page draft.

## Major changes

1. Added a quantitative frozen baseline table to the main Results section.
2. Added a quantitative real-matrix ablation table and separated neutral real
   ablations from seven deterministic synthetic mechanism-isolation cases.
3. Defined revision criticality as the worst normalized certificate/tolerance
   ratio, with critical boundary one.
4. Recast the Gaussian finite-edit image bound as Proposition 1 with explicit
   assumptions, a main-paper proof sketch, and a fuller supplementary derivation.
5. Strengthened related work with bounded-error incremental ray-traced editing,
   dependency-graph scene rendering, self-adjusting computation, and
   goal-oriented error estimation.
6. Made the absence of paired end-to-end LOCAL-vs-FULL timing explicit.
7. Simplified the explanatory Gaussian poster and replaced universal wording
   with "Certified under the stated assumptions" and fail-closed language.
8. Removed review line numbers from the author-visible build while retaining
   commented double-blind review instructions.
9. Fixed macro-spacing and mechanical table/equation issues.
10. Added explicit discussion that zero selected residuals do not measure bound
    tightness.

## Evidence discipline

No frozen experiment was retuned. Baseline and ablation numbers are copied from
the canonical public-v2.1 artifact. The baseline-suite native work ratio
(0.047357...) is labeled separately from the public heterogeneous
millisecond-calibrated headline ratio (0.369530...).


11. Rebuilt Figure 2 as a publication-native vector version of the approved
    "How Local Gaussian Revisions Propagate" visual. The new layout preserves
    the complete state progression and LOCAL/FULL decision branches while
    enlarging print-critical labels and replacing illustrative micro-metrics
    with verified frozen public-v2.1 headline evidence.
12. Enabled the manuscript build workflow on `main` so final source changes
    regenerate PDF, DOCX, and package artifacts without a branch-only handoff.
