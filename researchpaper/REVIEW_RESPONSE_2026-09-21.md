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


## Final manuscript-only correction

The earlier vector recreation is superseded by the exact author-supplied PNG.
It is embedded unchanged, with a recorded SHA-256 in `README.md`. The Figure 2
caption distinguishes illustrative embedded numbers from frozen campaign results
and limits the image's correctness wording to the stated assumptions.

All tables now use bounded widths with reduced padding. Table 3's long note is
outside the tabular grid, so it cannot widen the table into the adjacent column.
Wide baseline and ablation headers wrap; numerical entries remain aligned.

The normalized criticality definition now handles zero tolerance explicitly;
a numerical denominator floor must not relax the acceptance condition.
The temporal expression is stated as an upper bound, and the Gaussian assumptions
explicitly include the background in the shared bounded color interval.
These are manuscript corrections, not changes to the planner or frozen evidence.

The earlier statement that the manuscript workflow builds on `main` was incorrect
for the checked-out repository. This pass rebuilds locally and leaves all files
outside `researchpaper/` unchanged. See `MANUSCRIPT_QA.md` for verification.
