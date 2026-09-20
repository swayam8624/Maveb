# CBRC implementation and execution plan

Status: frozen execution plan for `research/maveb-cbrc-implementation`.
Problem: MAVEB-CLOSURE.
Method: Criticality-Bounded Revision Cones (CBRC).

## Paper claim boundary

The paper does **not** claim novelty for dependency graphs, Green's functions/resolvents, generic susceptibility, Gaussian error metrics, regional invalidation, or incremental rendering. The candidate contribution is the captured-world construction:

physical revision -> exact hard closure -> conservative heterogeneous soft transfer -> certified frontier residual -> minimum-work repair cone -> QoI certificate -> automatic full rebuild.

No Tier-1 acceptance or worldwide novelty is guaranteed. The branch is a falsification line.

## Implementation tracks

### T0 - reference certificate engine

Deliver an auditable Python implementation of:

1. non-negative tolerance-normalized transfer matrix `K_cert`;
2. exact predecessor/admissibility closure;
3. exterior response `G_O=(I-K_OO)^-1` only when the response certificate is valid;
4. frontier flux `f_O=b_O+K_OC z_C`;
5. per-QoI bounds `B_j`;
6. transient amplification and susceptibility diagnostics;
7. greedy certified cone expansion;
8. automatic full-rebuild fallback.

This implementation is a mathematical oracle/reference, not the production sparse runtime.

### T1 - typed edge registry

Every pipeline edge must be declared as exactly one of:

- HARD: identity, ownership, topology, provenance, insert/delete semantics, GPU record identity.
- ANALYTIC: conservative bounded soft influence; allowed in `K_cert`.
- EMPIRICAL: measured/predicted sensitivity; allowed for ordering only, forbidden from certification.

A run must fail closed if a certificate path contains an undeclared or empirical-only edge.

### T2 - layer-specific certified gains

Derive and unit-test gain constructors in this order:

1. Gaussian -> image: alpha/transmittance bound including changed foreground visibility of unchanged background.
2. Temporal history -> image: stable blend/reprojection support; disocclusion is HARD invalidation.
3. Texture/filter page -> image: bounded filter footprints; address/page identity is HARD.
4. TSDF -> mesh: truncation/ownership hard support first; soft interpolation only if a conservative finite-change bound is derived.
5. Mesh -> Gaussian/material state: initially HARD unless a useful analytic bound is proven.
6. GPU publication: HARD only.

Any edge whose conservative bound is too loose stays HARD. Safety beats cone size.

### T3 - sparse production representation

Replace the dense reference matrix by a typed sparse graph:
`RevisionNode`, `RevisionEdge`, `HardClosure`, `CertificateFrontier`, `QoIContract`, `WorkLedger`.

Required operations: predecessor closure; sparse frontier expansion; exterior solve/finite DAG path sum; bound accumulation in native tolerance units; deterministic serialization of the certificate; replay/check against the full rebuild oracle.

### T4 - transaction integration

For every physical revision:

1. ingest changed evidence;
2. form hard closure;
3. compute/lookup certified edge gains;
4. select a candidate cone;
5. execute repair in dependency order;
6. publish GPU state atomically;
7. invalidate required temporal state;
8. emit `RevisionCertificate.json`;
9. for evaluation only, run the full rebuild oracle;
10. compare actual error with certificate.

The full rebuild result is never used to choose the cone in the measured method.

## Frozen benchmark design

### Controlled 750-cell matrix

5 scene sizes x 5 edit classes x 5 magnitudes x 3 coupling regimes x 2 QoI tolerances = 750 cells.

Scene sizes: tiny, small, medium, large, stress.
Edit classes: geometry, appearance, Gaussian-state, publication/layout, temporal-history.
Magnitudes: 2%, 5%, 10%, 20%, 40% source extent.
Coupling: low, medium, high.
QoI tolerance: strict, practical.

Pilot: one repeat per cell or the compact `--pilot` matrix.
Final synthetic campaign: >=30 seeded repeats/cell where inexpensive.
Real captured-world campaign: repeated edits per scene with identical before/after inputs for every method.

### Required methods

- FULL: full rebuild oracle.
- EXACT: exact Boolean dependency closure / from-scratch-equivalent incremental work.
- RADIUS-r: fixed spatial/graph radius, several radii.
- FRACTION: changed-fraction heuristic.
- EMPIRICAL: empirical influence scheduler with no certificate.
- CBRC: certified minimum-work frontier with fallback.

Do not label an uncertified baseline "wrong"; report its measured error/work tradeoff.

## Primary metrics

Correctness/certification: actual QoI error, certified QoI bound, certificate violation, tolerance violation, effectivity, and full-reference equivalence for all HARD state.

Work: native work per layer from LocalityLedger, normalized work ratio to FULL, wall/GPU time, bytes published, blocks/patches/Gaussians/pages/history tiles touched, and peak memory.

Propagation diagnostics: cone fraction, hard-closure fraction, transient amplification, exterior susceptibility, shell response/correlation length, and local-to-full fallback point.

## Statistical protocol

Predeclare seeds and scene/edit manifests. Pair methods on exactly the same revision. Report median, IQR, bootstrap 95% CI, and per-scene distributions; do not rely on means alone. Separate planning overhead from repair work. Report warm and cold-cache runs. Never discard fallback trials.

## Figures required before performance claims

F1. actual error vs certified bound, with the y=x safety line. Any certified point above the line is a correctness failure.
F2. work ratio vs changed fraction, faceted by propagation coupling.
F3. same physical edit size under low/high coupling showing different cone size.
F4. automatic local -> full crossover.
F5. certificate effectivity distribution.
F6. per-layer work ledger stacked bars.
F7. cone visualization plus screen-space residual map.
F8. adversarial revisions that force conservative fallback.

## Implementation-complete gate before paper prose

Paper drafting may begin when all are true:

- reference certificate unit tests pass;
- typed edge registry exists and fails closed;
- at least Gaussian and temporal gain paths are integrated end-to-end;
- certificate artifact is emitted by a real revision;
- full rebuild oracle can replay the same revision;
- at least one real scene produces `actual <= bound <= epsilon`;
- at least one adversarial/high-coupling case triggers full fallback;
- all benchmark rows are machine-readable and reproducible;
- limitations/kill criteria are frozen.

Writing can start at that point even while the large final matrix continues. Do not write final performance claims before measurements exist.

## Kill criteria

Kill or demote CBRC if a supposedly certified run violates `actual <= bound`; safe gains require essentially running the full reference; useful edits almost always expand to full rebuild; certified cones are not materially smaller than exact closure; effectivity is operationally useless; planning overhead erases repair savings; or a closer prior result already contains the same captured-world certified frontier construction.

## Branch policy

Keep until the integration PR lands:
- `research/maveb-s1-locked`
- `research/maveb-revision-criticality`
- `research/maveb-cbrc-implementation`
- `research/maveb-gaussian-gpu-patch` (separate product/performance work)

After the locked integration is in `main` and CBRC is rebased/merged, archive tags may be created and obsolete `research/maveb-*`, `tmp-ignore*`, and superseded experiment branches can be deleted only after a compare confirms no unique commits/files remain. Never delete a branch merely because its name looks obsolete.
