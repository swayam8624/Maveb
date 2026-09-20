# CBRC v1 implementation status

Status: **implementation complete; empirical campaign pending**
Branch: `research/maveb-cbrc-implementation`
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

## What is still pending

The following are **experiments, not implementation tasks**:

1. provide one or more real captured persistent-world archives with Gaussian/ownership revision sidecars;
2. freeze real hardware work-cost coefficients from isolated microbenchmarks;
3. run the real campaign;
4. collect at least one certified local case;
5. collect at least one deliberate high-coupling/adversarial FULL fallback;
6. verify every certified real row satisfies `actual <= bound <= epsilon`;
7. run the larger repeated matrix and produce final statistics/figures;
8. write performance/result claims from those measurements.

Fixtures, randomized theorem probes and synthetic matrices may validate implementation behavior, but they do not substitute for these real measurements.

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
