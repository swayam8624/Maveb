# CBRC v1 implementation status

Status: **v1 implementation and paper-grade evidence package complete; paper drafting remains**
Canonical target: `main` (integration developed on `research/maveb-cbrc-implementation`)
Method: Criticality-Bounded Revision Cones (CBRC)
Problem: MAVEB-CLOSURE

This file distinguishes completed engineering from measurements that still require real captured scenes.

## Completed v1 scope

### T0 — auditable reference planner

Complete.

- Dense Python certificate engine with non-negative analytic transfer.
- Exact predecessor closure.
- Finite exterior response.
- Per-QoI bounds.
- Greedy certified feasible-cone search.
- Independent FULL-work baseline.
- Full-rebuild fallback.
- Effectivity and susceptibility diagnostics.
- Regression coverage for zero-work nodes, independent FULL baselines, unsafe cycles and complete regional cones.

The Python implementation is the reference/falsification implementation, not the production performance path.

### T1 — typed dependency semantics

Complete.

Every dependency used by the planner is one of:

- **HARD** — exact structural dependency.
- **ANALYTIC** — conservative finite-change upper bound.
- **EMPIRICAL** — scheduling information only; promoted to exact for certification.

Analytic edges require explicit bound provenance. Empirical edges cannot silently certify.

### T2 — implementation-backed layer bounds

Complete for the v1 soft-bound scope.

Analytic:

- Gaussian revision -> current image, including edited termination/transmittance effects.
- Stable temporal history/current image -> resolved image.

Exact/HARD by design in v1:

- observation -> TSDF;
- TSDF -> mesh ownership/support;
- mesh -> texture page identity;
- texture page -> material state identity;
- Gaussian source record -> GPU publication;
- temporal validation discontinuities/disocclusion.

These exact edges are **not unfinished soft-bound work**. V1 intentionally refuses to introduce weaker analytic approximations where no useful conservative theorem is implemented.

### T3 — sparse native planner

Complete.

- C++23 `RevisionGraph`, typed nodes/edges/QoIs.
- Sparse O(V+E) analytic DAG propagation.
- Exact predecessor consistency.
- Independent full-reference work baseline.
- Greedy certified cone selection.
- Fail-closed analytic-cycle behavior.
- Complete regional cone is distinct from FULL reference rebuild.
- Deterministic native certificate JSON serialization.
- Native/Python parity gate in campaign execution.

Cyclic analytic resolvent support is deferred to a later version; v1 expands the cone or rebuilds rather than certifying an unsupported cycle.

### T4 — transaction and evidence integration

Complete for v1.

Production/live path:

- indexed persistent Gaussian entity translation;
- immutable before/after Gaussian revision sidecars;
- exact camera binding;
- production Gaussian image certificate;
- temporal support coverage validation;
- planner-selected temporal repair/retention;
- atomic/fail-closed fallback behavior;
- Studio bridge evidence JSON.

Headless path:

- persistent-world load;
- indexed Gaussian transaction;
- durable new world revision and sidecars;
- Gaussian certificate;
- output-cone planner;
- canonical native planner certificate;
- translation/certificate evidence JSON.

Heterogeneous planning path:

- `LocalityLedger` is the counter source of truth;
- observation, TSDF, mesh, texture page, material, Gaussian, GPU publication and temporal domains are registered;
- ledger/mesher disagreement fails closed;
- heterogeneous native-unit work is converted only through a frozen, versioned scalar cost model.

### Oracle, replay and campaign

Complete.

- Independent full-reference Gaussian oracle.
- Per-pixel actual error and certified bound output.
- Strict `actual <= bound <= epsilon` evaluator.
- Production/offline certificate agreement check.
- Immutable evidence-bundle hashing.
- Real-campaign runner.
- Native/Python planner parity gate.
- Baseline suite: FULL, EXACT, RADIUS-0..3, FRACTION, EMPIRICAL, CBRC.
- Required structural/analytic/fallback/QoI ablations.
- Automatic campaign gates for local success, high coupling, FULL fallback and zero certificate violations.
- Deterministic F1-F8 figure sources and method-comparison tables.

### CI / regression state

The v1 line is expected to pass:

- warnings-as-errors CPU build and CTest;
- sanitizer build and tests;
- changed-file static analysis;
- format/lint;
- MavebBench tests;
- research evaluation tests;
- iPad capture compile;
- macOS AetherStudio compile.

A failure in any certificate correctness regression blocks evidence claims.

## Frozen v1 evidence status

The v1 implementation has now completed its frozen paper-grade evidence campaign.

- public v2.1: 60 revisions across four public RGB/SfM scenes;
- 44 certified-local cases and 16 automatic FULL fallbacks;
- zero observed certificate violations;
- native/Python parity on all 60 revisions;
- 56/60 source edits visibly exceed the protected RGB tolerance before repair;
- frozen heterogeneous millisecond cost calibration plus separately recorded phase wall times;
- exact sparse-discovery scaling through 1,000,000 Gaussians;
- held-out empirical scheduling protocol;
- baseline/ablation suite and SIGGRAPH-oriented evidence visual package;
- pinned public trained-3DGS validation with 5 revisions, 4 certified-local cases, 1 FULL fallback and zero certificate violations.

The measured public-campaign median calibrated heterogeneous work is approximately 0.349 of FULL. This is a **calibrated work estimate**, not a paired end-to-end speedup. The trained-3DGS campaign reports a median native temporal/output work ratio of approximately 0.03495, likewise not a wall-clock speedup.

A measured systems limitation remains visible rather than hidden: the frozen end-to-end campaigns still inspect nearly the full Gaussian set. A separate exact sparse-discovery sweep demonstrates substantially smaller inspection fractions, so integrating that index into the complete measured campaign is a future optimization rather than part of the current claim.

The remaining work for the current paper line is scientific writing, figure selection/captioning, related-work positioning, and submission packaging—not missing CBRC v1 implementation or missing frozen core evidence.

## Explicitly deferred v2 work

These are optional future research directions and are outside the completed v1 implementation:

- certified cyclic analytic resolvent support;
- formal texture-filter soft bounds;
- useful conservative TSDF interpolation soft bounds;
- mesh/material soft approximations;
- learned/empirical ordering beyond conservative scheduling;
- global combinatorial minimum-work optimization;
- GPU-native heterogeneous planner execution.

None is required for v1 correctness because v1 fails closed or keeps the corresponding relation HARD.
