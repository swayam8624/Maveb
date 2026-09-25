# MAVEB Final Manuscript Audit — 2026-09-25

This audit supersedes the 2026-09-22 claim/method/citation audit for the current manuscript. The older audit is retained as historical traceability for the earlier public-pilot paper state.

## Scientific headline bound to the manuscript

The current source reports the frozen paper-grade campaign and the separately frozen residual-sensitive sequence.

### Broad systems campaign

- 1,275 revisions over 85 scenes.
- Dataset / representation groups: 40 3RScan scenes (600 cases), 20 ARKitScenes scenes (300 cases), 12 Bonn RGB-D Dynamic scenes (180 cases), and 13 pinned trained GraphDECO 3DGS scenes (195 cases).
- 935 certified LOCAL repairs and 340 automatic FULL fallbacks.
- 73.33% LOCAL, Wilson 95% CI 70.84–75.69%.
- Zero observed certificate violations.
- Median calibrated selected work/FULL = 0.47447, bootstrap 95% CI 0.46657–0.47885.
- 1,275/1,275 selected renders are byte-identical to independent FULL-after on the audited benchmark views.
- Edit families: opacity, rotation, translation, and uniform scale.
- Coupling regimes contain both LOCAL and deliberate fail-closed FULL outcomes; adversarial coupling is not hidden from the result.

The work ratio is a calibrated heterogeneous work metric, not a paired end-to-end wall-clock speedup.

### Residual-sensitive sequence

- **v4 diagnostic:** 512 frozen cases. Every non-zero-residual case falls back to FULL, exposing the magnitude-insensitive certificate as the bottleneck.
- **v5 mechanism study:** opacity-only residuals use the delta-sensitive display certificate while translation stays on the legacy envelope as a control. It produces 142 certified non-zero LOCAL opacity cases and 29 tolerance-crossover keys; translation produces zero non-zero LOCAL cases.
- **v6 confirmation:** unchanged v5 mechanism over 20 independently selected scenes, five from each dataset / representation family, with 3,840 pooled parameter cases. All predeclared confirmatory gates pass.
- Non-zero opacity locality and opacity tolerance crossover occur in all 20 scenes.
- Scene-level opacity non-zero-local rate = 0.477, dataset-stratified bootstrap 95% CI [0.432, 0.517].
- Translation non-zero-local rate = 0.000 [0.000, 0.000].
- Paired opacity-minus-translation scene-level difference = 0.477 [0.432, 0.517].
- Generic v6 audit contains 687 certified non-zero LOCAL cases and 151 tolerance-crossover groups.
- No accepted v6 case is near the tolerance boundary: the largest scene maximum of measured residual/epsilon is 0.0812; median scene-level residual effectivity is about 1168.

The last two measurements are retained as evidence that the current certificate is conservative rather than presented as a tight estimator.

## Novelty boundary

The manuscript does not present graph closure, self-adjusting computation, norm bounds, Neumann-series reasoning, or goal-oriented error estimation as new mathematics. The claimed contribution is the captured-world revision contract that binds:

- exact structural closure;
- conservative finite-change exterior accounting;
- output-specific tolerances;
- calibrated work crossover;
- fail-closed FULL fallback;
- immutable revision/evidence records; and
- independent full-after falsification

to the same repair decision.

## Citation integrity

Static source audit after final cleanup:

- 28 unique citation keys used by `main.tex`.
- 28 bibliography entries in `references.bib`.
- Missing cited keys: 0.
- Unused bibliography entries: 0.

The three public-pilot-only entries for COLMAP/SfM, Tanks & Temples, and Deep Blending were removed from the current bibliography because they are no longer cited by the final manuscript. Their historical evidence remains in repository history.

Recent related-work records used by the final text were separately checked against CVF or arXiv records, including GaME (CVPR 2026), Consistent Instance Field (CVPR 2026), From Pixels to Primitives (arXiv:2605.07203), and EliGSiR (arXiv:2609.20348).

## Source-structure audit

Current `main.tex` contains:

- 2 manuscript figures;
- 6 content tables;
- 18 numbered displayed equation environments;
- the final v4, v5, and v6 evidence directly in the source;
- the generative-AI-use disclosure;
- no `TODO`, `TBD`, `FIXME`, or placeholder markers;
- no legacy 60-case/44-LOCAL work headline; and
- no conditional `reviewer-v2` manuscript path.

## Claim boundaries that must remain intact

The manuscript does not claim:

- universal safety;
- guaranteed tolerance satisfaction outside the stated assumptions;
- wall-clock speedup from the calibrated-work metric;
- globally minimum-work cones;
- semantic ownership where the implementation uses deterministic/spatial bookkeeping;
- source-photograph reconstruction accuracy from selected-to-FULL raster equality;
- independence of all 3,840 v6 parameter cases; or
- venue acceptance.

Scene-level, dataset-stratified inference is the primary v6 statistical unit.

## Release synchronization

The scientific source was updated on 2026-09-25 after the previously committed PDF/DOCX/supplement/checksum set from 2026-09-22. Therefore the September 22 binaries are historical and must not be treated as the final release for this source.

A synchronized release must:

1. build `main.tex` and the supplement from the current commit;
2. pass the structural checks in `build_manuscript.py`;
3. contain the exact Figure 2 bytes;
4. produce two figures, six editable DOCX tables, and eighteen editable displayed equations;
5. contain no overfull box, undefined reference/citation, multiply-defined reference, or missing-character failure caught by the builder;
6. record fresh SHA-256 checksums for PDF, DOCX, and supplement; and
7. pass rendered visual inspection of every page before publication.

The repository’s 2026-09-24 broad claim ledger has also been marked explicitly: its broad-campaign values remain current, while its pre-v6 conditional reviewer boundary is historical and superseded by this audit.

The generated artifacts and their checksum manifest become release-valid only after those gates pass for the current source state.
