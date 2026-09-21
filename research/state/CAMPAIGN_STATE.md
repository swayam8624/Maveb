# MAVEB Discovery Campaign State

Updated: **2026-09-20 22:00 IST**

## Problem lock

The exploration phase is closed for the current paper.

**Locked problem:** MAVEB-CLOSURE — dependency-certified heterogeneous minimal-work repair for
persistent captured worlds.

**Locked method identity:** Criticality-Bounded Revision Cones (CBRC), emitting a Cross-Derived-State Revision Certificate (CDSRC) for each accepted repair.

The paper asks whether one localized physical-world revision can trigger a conservative dependency
closure spanning observations/evidence, TSDF, explicit mesh, Gaussian state, texture/material state,
GPU publication and temporal history, while matching a declared full-reference result and making
work scale with affected state instead of total world size.

See `research/state/PROBLEM_LOCK.md`.

## Consolidated branch

All current-paper work is consolidated on the final integration line and is intended to land on:

`main`

Historical branches are provenance only and are not active execution sources.

The locked line now contains:

- persistent/indexed Gaussian local selection;
- unit-safe cross-layer LocalityLedger;
- observability-safe persistent-world semantics;
- stable-atlas correctness oracle;
- persistent locality-aware texture page allocator;
- versioned per-frame Gaussian GPU publication;
- conservative regional temporal-history invalidation;
- temporal representation oracle probe;
- resampling-lineage downstream probe;
- VG-Scene local adapter + MavebBench integration;
- S1 evaluator, frozen 750-cell experiment matrix and SVG evidence generator;
- literature/mining/hypothesis/negative-result campaign evidence.

## Corpus and filter

- Literature corpus: **52 papers**
- Mined implementations: **18 repositories**
- Hypotheses: **119**
- Locked headline hypotheses: **5**
- Required mechanisms: **16**
- Evaluation/ablation hypotheses: **6**
- Deferred follow-ups: **92**

The headline set is H027, H029, H030, H035 and H118.

See `research/hypotheses/final_filter_2026-09-20.md`.

## Novelty boundary

The current paper does **not** claim novelty for local Gaussian optimization, hybrid TSDF+Gaussian
mapping, persistent Gaussian/object identity, virtual texturing, sparse GPU publication, regional
TAA invalidation, Gaussian streaming/deltas, dependency graphs, or self-adjusting scene-graph
rendering by themselves.

Those ideas are prior art or enabling mechanisms. HPG 2013 work on lazy incremental scene-graph
rendering already used dependency-driven render-cache propagation, so dependency graphs/change
propagation themselves are explicitly outside the novelty claim.

The surviving candidate contribution is the **end-to-end captured-world closure and certificate**:
physical evidence change → heterogeneous derived-state closure → bounded repair → native-unit work
ledger → full-reference equivalence.

This remains a candidate contribution until closest-prior-art search and experimental evidence pass
the lock gates.

## What is already real

- Exact sparse TSDF→mesh incremental correctness exists.
- Controlled Gaussian region-index probes show exact selection agreement and large inspection
  reduction in sparse fixtures.
- Stable fixed-capacity atlas correctness is proven, while that architecture was rejected for scale.
- Naive page-level texture rewriting was rejected; locality-coherent allocation survived the cheap
  probe and a production-shaped persistent allocator now exists.
- Versioned per-frame Gaussian publication removes edit-time all-frame quiescence on the locked line.
- Regional temporal-history invalidation uses conservative projected edit support and unions multiple
  pending edits.
- The S1 evaluator rejects missing headline layers, hidden sparse global work and failed
  full-reference equivalence.
- VG-Scene is a runnable local benchmark target, subject to external dataset/license availability.

## Required next evidence

1. Green CI / Studio / sanitizer validation for the consolidated locked head.
2. Bind every required layer to one CBRC repair transaction and emitted CDSRC artifact.
3. Run Apple-silicon sparse-change measurements.
4. Execute the frozen 750-cell controlled matrix.
5. Run public evolving-scene experiments including VG-Scene where licensing permits.
6. Compare full rebuild and strongest task-compatible continual/changing-scene baselines.
7. Run mechanism ablations.
8. Characterize the crossover where local repair should fall back to a full rebuild.
9. Produce figures only from committed raw results.

## Research integrity

No numeric result is promoted unless the corresponding committed experiment actually executed.
Synthetic/Linux/Python results remain labelled as such and are never reported as Apple-silicon or
production measurements.

A previously created unexecuted Gaussian-overlay result was deleted and the correction remains
recorded in `research/LOG.md`.

## Status

PROBLEM_LOCKED = true
METHOD_IDENTITY_LOCKED = true
HYPOTHESIS_FILTER_COMPLETE = true
CLAIM_PROVEN = false
PAPER_READY = false
