# MAVEB S1 Problem Lock — MAVEB-CLOSURE

**Locked:** 2026-09-20  
**Status:** problem/method identity locked; experimental claim not yet proven  
**Paper-ready:** false

## The locked problem

A persistent captured-world system does not maintain one representation. One physical-world revision
can invalidate evidence/observations, volumetric fusion, explicit surface geometry, Gaussian state,
texture/material state, GPU-published records, and temporal render history.

Existing continual-mapping systems can localize one or several of those layers, while older
incremental-rendering systems can propagate scene-graph changes into rendering caches. Neither fact
is enough for MAVEB.

The locked research question is:

> Given a localized physical-world revision Δ, can a captured-world system compute a conservative
> cross-derived-state dependency closure C(Δ), repair only C(Δ), and produce the same declared world
> result as a full reference rebuild while making work scale with affected state rather than total
> world size?

The novelty target is **not** local Gaussian optimization, persistent IDs, TSDF+Gaussian mapping,
virtual texturing, incremental GPU uploads, regional TAA invalidation, or dependency graphs by
themselves. Those are occupied ideas and are mechanisms only.

## Method identity: MAVEB-CLOSURE

MAVEB-CLOSURE is a revision-scoped repair protocol over a heterogeneous captured-world dependency
graph.

A revision is accepted only after the system:

1. records the changed evidence and observability state;
2. computes the conservative dependency closure over derived world state;
3. repairs only closure members using stable region/entity/patch/record identities;
4. publishes only stale GPU records into safe recycled frame resources;
5. invalidates only temporal history whose conservative projected support intersects the revision;
6. measures incremental and full-reference work independently in native units for every headline
   layer; and
7. verifies the declared incremental/full-reference equivalence contract before committing the
   revision.

The core scientific object is therefore a **Cross-Derived-State Revision Certificate (CDSRC)**:

    revision Δ
      + dependency closure C(Δ)
      + per-layer incremental/full work ledger
      + output-equivalence verdict
      + unchanged-world damage evidence
      = one certified repair transaction

## Headline hypotheses

Only these five hypotheses may carry the paper's primary claim:

- **H027 — Cross-representation atomic repair**
- **H029 — Minimal-work proof oracle**
- **H030 — Changed-fraction scaling law**
- **H035 — Dependency-driven full-pipeline ULR**
- **H118 — End-to-end work locality has a sparse-change regime**

All other hypotheses are mechanisms, evaluation, or follow-up work.

## Required mechanism set

These are required to make the headline claim executable, but they are not standalone novelty claims:

- H021 observation→TSDF closure
- H022 TSDF→mesh closure
- H023 mesh→Gaussian closure
- H024 direct observation→Gaussian closure where applicable
- H025 texture dependency repair
- H026 render-resource transitive closure
- H028 dependency-closure compression
- H031 occlusion-aware repair
- H034 semantic-only zero-geometry repair
- H053 observability-gated deletion
- H082 region-resident/shared GPU buffers
- H091 region-delta snapshots
- H102 Update Locality Ratio instrumentation
- H116 compact Gaussian base + bounded relocation delta
- H117 stable texture addressing with local write granularity
- H119 dependency-coherent texture pages

## Explicit novelty boundary

The paper must **not** claim novelty for any of the following:

- generic continual/local 3D Gaussian map updates;
- TSDF-guided changed-region Gaussian repair;
- object-level Gaussian asset maintenance;
- updating only changed semantic object submodels;
- persistent Gaussian density/identity alone;
- Gaussian snapshots/incremental delivery;
- dependency graphs or self-adjusting computation in rendering;
- stable texture addresses/virtual texturing;
- sparse GPU record upload;
- regional temporal-history invalidation by itself.

The paper claim must remain the end-to-end captured-world closure + certificate.

## Closest collision classes

The final literature attack must continuously compare against:

- continual/local Gaussian mapping and editing;
- hybrid TSDF + Gaussian change-aware mapping;
- object-centric lifelong Gaussian maintenance;
- semantic object-submodel update methods;
- persistent-density Gaussian representations;
- incremental Gaussian streaming/delivery;
- incremental scene-graph/render-cache dependency systems;
- self-adjusting/incremental computation.

If a paper is found that already performs the same captured-evidence→reconstruction→surface→radiance/
texture→GPU-publication→temporal-history closure **and** reports equivalent full-reference output with
per-layer work certification, this lock is invalid and the campaign must reopen.

## Frozen evaluation contract

### Changed fractions

0.1%, 0.25%, 0.5%, 1%, 2%, 5%, 10%, 25%, 50%, 100%.

### Change classes

addition, removal, rearrangement, geometry, appearance.

### Scene scales

small, medium, large.

### Required evidence

For every evaluated revision:

- changed-world support;
- per-layer incremental work;
- equivalent full-reference work;
- per-layer ULR;
- CPU and GPU wall time where measurable;
- CPU↔GPU publication bytes;
- peak memory;
- output-equivalence verdict;
- unchanged-world damage;
- provenance: dataset/scene/revision/config/git SHA/hardware.

Native work units may never be collapsed into one synthetic scalar.

## Tier-1-grade success gates

These are **predeclared targets**, not current results.

1. **Correctness:** exact equality for discrete ownership/dependency/selection semantics; explicit
   tolerance contracts for geometry/render outputs.
2. **No hidden global stage:** at sparse changes, no headline layer may silently perform full-world
   work while being omitted from the certificate.
3. **Sparse-regime benefit:** on multiple held-out scenes, 1–5% physical changes must yield a clear
   end-to-end work/latency advantage over the equivalent full reference, not merely one faster
   subsystem.
4. **Quality preservation:** incremental repair must remain statistically indistinguishable from, or
   within the predeclared tolerance of, the full reference on the metrics being claimed.
5. **Unchanged-world preservation:** work savings cannot come from allowing damage or stale state
   outside the affected closure.
6. **Generality:** the result must hold across multiple change types and both synthetic-controlled
   and public/real evolving scenes.
7. **Ablation:** removing Gaussian indexing, coherent texture allocation, versioned publication,
   observability semantics, or regional history must expose the corresponding hidden-global or
   correctness failure.
8. **Closest-baseline comparison:** compare against full rebuild and the strongest compatible
   continual-Gaussian / changed-region methods whose code/data and task contracts permit fair
   reproduction.
9. **Crossover characterization:** report where local repair stops winning; do not hide the
   full-rebuild crossover.
10. **Reproducibility:** configs, raw results, negative results, figures, and exact commit hashes
    must be retained.

## Kill conditions

Kill or substantially reformulate the locked paper if any of the following occurs:

- the full cross-derived-state claim is found already occupied by prior work;
- one unavoidable layer remains near full-world work for sparse revisions and dominates end-to-end
  cost;
- equivalence requires routine global rebuilds in the sparse regime;
- benefits disappear on public/real evolving scenes;
- the method wins only against weak or task-mismatched baselines;
- local repair causes measurable unchanged-world damage that the full reference does not;
- the result reduces to a known incremental-computation system with no captured-world-specific
  algorithmic or empirical contribution.

## What is not promised

No problem formulation can guarantee acceptance at SIGGRAPH, SIGGRAPH Asia, CVPR, ICCV, HPG, I3D,
TVCG, or any other Tier-1 venue. Reviewer decisions depend on novelty, evidence, presentation,
timing, and competition. This lock is intended to maximize the chance of a defensible Tier-1-level
submission by making the claim narrow, falsifiable, difficult to explain away, and aggressively
benchmarked.

PROBLEM_LOCKED = true  
METHOD_IDENTITY_LOCKED = true  
CLAIM_PROVEN = false  
PAPER_READY = false
