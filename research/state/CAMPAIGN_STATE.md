# MAVEB Discovery Campaign State

Updated: **2026-09-20 20:24 IST**

## Current center of gravity

The strongest surviving direction remains **S1 — dependency-certified heterogeneous minimal-work
repair**. The campaign is now explicitly separating three things:

1. semantic locality — only the intended world region should change;
2. computational locality — work/bytes/synchronization should scale with the affected dependency
   closure rather than total world size;
3. correctness equivalence — where equivalence is claimed, the incremental result must match the
   declared full reference within an explicit exact/tolerance contract.

No one local subsystem is a headline contribution by itself.

## What is now real

- Literature corpus: **47 papers**; mined implementation ledger: **17 repositories**.
- Hypothesis database: **119 hypotheses**.
- `research/maveb-discovery-persistent` contains production-shaped indexed Gaussian selection.
  At head `535d1f1`, CPU build/tests, sanitizers, iPad compile and AetherStudio compile passed;
  formatting/static-analysis issues were fixed at `f6a307b` and the rerun is queued.
- `research/maveb-ulr-ledger` now contains a unit-safe per-domain work ledger plus Gaussian
  inspection instrumentation. CI is pending; no result claim yet.
- `research/maveb-observability` contains explicit absence-evidence semantics for preserving
  unobserved entities. Full validation is pending.
- `research/maveb-stable-atlas` is **fully CI green** and proves stable-slot UV addressing as a
  correctness mechanism.

## New falsification results

### Compact base + relocation delta

An executed NumPy reference probe at one million primitives preserved exact selected primitive IDs
for cumulative 1/2/5/10/20/40% relocation. Small deltas are structurally cheap to rebuild, but
overlay query/storage overhead grows. This promotes the mechanism to production A/B testing only;
it is not Apple-silicon or paper evidence.

### Fixed global stable atlas — rejected for scale

The implementation is correct, but reserving one global fixed slot space collapses per-slot texture
resolution at large capacities. Keep it as a correctness oracle, not the scalable architecture.

### Naive stable pages — rejected

With 250k active slots and **1% randomly scattered changes**, whole-page rewrite fractions were
about 47% (64 slots/page), 92% (256), and ~100% (1024/4096). A clustered 1% change stayed near 1%.

Therefore texture locality requires **dependency/spatially coherent page assignment and/or sub-page
writes**. Stable addresses alone do not imply local work.

## Novelty pressure

2026 work such as GaME, LTGS, CubifyGS, SI-Update and Eulerian Gaussian Splatting removes broad
claims around continual Gaussian updating, long-term chronology, reusable object assets, selective
changed-object repair, and primitive-index persistence. S1 survives only in its sharper
cross-representation/cross-derived-state form, and even that remains an unverified candidate claim.

## Immediate execution order

1. Finish indexed-selector CI and Apple-silicon benchmark.
2. Finish ULR ledger CI; attach exact counters layer by layer.
3. Finish observability correctness validation.
4. Replace naive texture paging with locality-coherent allocation/sub-page write probes.
5. Attack GPU publication quiescence/full-buffer reload.
6. Attack global temporal-history invalidation.
7. Only after real regional cost tuples exist, run representation-migration oracle.
8. Continue literature refresh and kill collisions immediately.

## Research integrity

A numeric overlay result was briefly created before the corresponding probe had actually executed.
It was deleted immediately and the correction is preserved in `research/LOG.md`. The subsequently
stored NumPy overlay result is from a real execution and is explicitly labeled with its runtime.

## Rule

Every future result must move a hard gate, kill/pivot a hypothesis, or improve evidence
infrastructure. Correct engineering without a measured research consequence is not a claim.

`PAPER_READY = false`
