# MAVEB External-Feedback Response Ledger — final v6 integration, 2026-09-25

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
**Status: resolved by the completed residual-sensitive sequence.**

The 1,275-case broad campaign remains exact on the audited views and is still reported that way. The residual-sensitive evidence is kept separate so the paper does not blur exact repair fidelity with tolerance-bearing approximation.

The final sequence is:
- **v4 diagnostic:** 512 frozen cases. Every non-zero-residual case falls back to FULL, exposing the magnitude-insensitive certificate as the bottleneck.
- **v5 mechanism study:** the physical edit matrix is retained while opacity-only residuals use the delta-sensitive image certificate and translation remains on the legacy envelope as a control. This produces 142 certified non-zero LOCAL opacity cases and 29 tolerance-crossover stress keys, while translation produces zero non-zero LOCAL cases.
- **v6 confirmation:** the unchanged v5 mechanism is repeated over 20 independently selected scenes, five from each of 3RScan, ARKitScenes, Bonn RGB-D Dynamic, and trained GraphDECO 3DGS. All predeclared confirmatory gates pass. Non-zero opacity locality and tolerance crossover occur in 20/20 scenes, and the paired opacity-minus-translation scene-level difference is 0.477 with a dataset-stratified bootstrap 95% interval [0.432, 0.517].

The manuscript also reports the negative boundary: no accepted v6 case is near the tolerance threshold, and the residual certificate remains conservative.

### Comment: show a real captured/dynamic scene and LOCAL-vs-FULL visual evidence
**Status: complete.**

The final v6 visual package was generated after the confirmatory audit. Four representative evaluated cases were selected deterministically with source-RGB resolvability first, followed by non-zero LOCAL evidence and dataset diversity. Original source RGB was resolved for the ARKitScenes, Bonn RGB-D Dynamic, and 3RScan examples; the trained GraphDECO case remains renderer-only. The figure caption keeps the scientific boundary explicit: source photographs provide captured-scene context, while MAVEB before/LOCAL/FULL panels are renderer outputs and are not presented as pixel-registered source-image comparisons.

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

## Finalization state

The scientific campaign is complete. The manuscript integrates the broad 1,275-case/85-scene systems evaluation and the frozen v4→v5→v6 residual-sensitive sequence directly; no conditional reviewer-v2 claim path remains.

Final release work is limited to manuscript production and verification:
1. compile the ACM PDF, editable DOCX, and supplement from the committed source;
2. reject any layout build with overfull boxes, undefined references, missing glyphs, or broken tables/figures;
3. keep the v4 negative result, v5 mechanism isolation, v6 scene-level statistics, and certificate-conservatism limitation unchanged during layout fixes;
4. perform the final claim/citation consistency pass and venue-specific anonymization when needed.

No additional broad campaign or extra multi-edit campaign is required by the current feedback.
