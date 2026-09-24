# MAVEB External-Feedback Response Ledger — 2026-09-24

This ledger maps the substantive external feedback received on MAVEB/CBRC to the current repository and manuscript state. It is intentionally conservative: an experiment is marked complete only when the corresponding frozen evidence exists.

## Kaan Akşit — novelty positioning and evaluation breadth

### Comment: make the CBRC contract itself the contribution
**Status: addressed in manuscript.**

The abstract, Introduction, Related Work, Discussion, and contribution list now state that dependency-aware recomputation, self-adjusting computation, norm bounds, and goal-oriented error estimation are prior ideas. MAVEB's claimed contribution is the captured-world revision contract that combines:
- exact structural closure;
- conservative finite-change exterior accounting;
- output-specific tolerances;
- frozen work crossover;
- fail-closed FULL fallback;
- immutable evidence/provenance;
- independent full-after falsification.

### Comment: broaden the realistic evaluation
**Status: complete.**

The paper-grade frozen campaign now contains:
- 85 scenes;
- 1,275 revisions;
- 40 3RScan worlds / 600 cases;
- 20 ARKitScenes worlds / 300 cases;
- 12 Bonn RGB-D Dynamic worlds / 180 cases;
- 13 pinned trained GraphDECO 3DGS scenes / 195 cases.

Observed result:
- 935 certified LOCAL;
- 340 FULL fallback;
- 0 observed certificate violations;
- 73.33% LOCAL, 95% CI 70.84–75.69%;
- median calibrated work/FULL 0.47447, bootstrap 95% CI 0.46657–0.47885.

### Comment: include trained photorealistic 3DGS
**Status: complete within the output-side revision scope.**

The main campaign now includes 195 cases over 13 pinned trained GraphDECO 3DGS scenes. This replaces the old five-case representation check as the primary trained-representation evidence.

### Comment: more edit types
**Status: complete.**

The frozen campaign contains:
- opacity: 255 cases;
- rotation: 340;
- translation: 340;
- uniform scale: 340.

All four families have zero observed certificate violations.

### Comment: statistical comparison
**Status: complete.**

The analysis now reports:
- Wilson 95% intervals for local/violation rates;
- 5,000-resample bootstrap confidence intervals for median work;
- paired baseline/ablation comparisons;
- exact two-sided sign tests where informative.

Against FULL, CBRC has lower calibrated work in 935 jointly certified cases and ties in 340; the exact sign-test p-value is 6.89e-282.

## Juncheng Liu — practical effectiveness / non-zero residual

### Comment: zero selected residual makes the tolerance contract look trivial
**Status: still open in the broad campaign; dedicated v2 machinery complete.**

The paper-grade broad campaign remains exact on the audited views:
- selected exact-case rate = 1.0;
- 1,275 / 1,275 selected renders are byte-identical to FULL-after.

This is preserved as a real limitation rather than reframed as certificate-tightness evidence.

Reviewer-v2 is now a separate frozen experiment that:
- renders a real hybrid Gaussian repair state;
- leaves a deterministic predeclared subset of changed Gaussians stale;
- independently certifies the omitted subset;
- measures the non-zero hybrid-vs-FULL residual;
- requires actual <= bound <= epsilon;
- fails the manuscript-readiness gate on any omitted-subset certificate violation;
- freezes epsilon sweeps before outcome inspection.

### Comment: show a real captured/dynamic scene and LOCAL-vs-FULL visual evidence
**Status: implementation complete; frozen v2 result still must be executed locally.**

The reviewer-v2 visual package generates:
- captured reference/rescan or temporal source context;
- before state;
- LOCAL selected repair;
- FULL result;
- absolute residual;
- certified support/bound visualization;
- fixed-edit tolerance crossover visualization when one exists.

The runner now emits a manuscript LaTeX block only when every reviewer-readiness gate passes. OPEN gates generate comments/status only, so the paper cannot accidentally claim a reviewer-v2 success that the run did not establish.

## Ulf Assarsson — corner cases and prose quality

### Comment: 44 successful cases looked too clean; include corner cases
**Status: addressed by the paper-grade campaign.**

The frozen decision envelope now contains genuine failure/corner regimes:
- low: 340 / 340 LOCAL;
- medium: 340 / 340 LOCAL;
- high: 170 LOCAL / 85 FULL;
- adversarial: 85 LOCAL / 255 FULL.

The paper presents these fallbacks as intended fail-closed behavior, not failed trials.

### Comment: manuscript cadence felt AI-like; many repeated "not" constructions
**Status: substantially addressed.**

The 2026-09-24 manuscript pass:
- reduces standalone "not" usage from 68 to 36;
- moves repeated defensive language into a smaller number of explicit limitation statements;
- rewrites the abstract, Evaluation, Results, Discussion, and Conclusion in direct positive constructions where scientifically equivalent;
- retains negative wording where it protects a real claim boundary.

## Remaining actions

1. Execute reviewer-v2 on the local prepared 85-world source tree.
2. Preserve the result even if one or more reviewer-readiness gates remain OPEN.
3. If reviewerEvidenceReady=true, commit the generated:
   - `researchpaper/generated/reviewer_v2_results.tex`;
   - `researchpaper/generated/reviewer_v2_status.md`;
   - reviewer-v2 figures copied into `researchpaper/figures/`.
4. Compile the manuscript and fix layout only; do not alter frozen evidence to make the story cleaner.
5. Perform a final claim/citation consistency pass before venue-specific formatting.

No additional broad campaign or extra multi-edit campaign is required by the current feedback: those requests are already covered by the completed 1,275-case frozen experiment.
