# MAVEB Medium-Strength Shortlist v0

**Date:** 2026-09-20  
**Stage:** first pruning from 115 hypotheses; not finalists and not novelty claims.

## S1 — Dependency-certified heterogeneous minimal-work repair

**Question:** Can one changed observation/world edit update only the transitive dependency closure across TSDF blocks, mesh patches, Gaussian clusters, textures/materials and GPU resources while matching an equivalent full rebuild?

**Why it survives:** MAVEB already has exact TSDF→mesh locality, PR #28 has Reality Diff and ownership-aware Gaussian locality, and the new RegionKey index probes show the hidden O(N) Gaussian scan can be removed in principle.

**Hard gate:** for small changed fractions, component ULR must scale with affected state rather than total world size, with no quality/equivalence regression.

## S2 — Certified non-target geometric preservation for local edits

**Question:** Can an edit to Ω carry an explicit measurable/certifiable bound on geometry damage outside Ω?

**Why it survives:** modern editors already localize edits, so the only defensible distinction is a stronger geometric preservation contract rather than another selective optimizer.

**Hard gate:** beat hard-freeze, rigidity, surface-anchor, density, ICP/OT and current editor baselines on Unchanged World Damage while preserving intended edit quality.

## S3 — Temporal representation migration

**Question:** Can regions switch TSDF ↔ mesh ↔ Gaussian over time as evidence, update frequency, view dependence and resource budgets change?

**Why it survives:** fixed hybrid representations are crowded, but temporal migration under continual-world objectives remains less directly occupied.

**Hard gate:** an offline oracle must Pareto-dominate the best fixed representation on real/synthetic temporal sequences before any online policy is built.

## S4 — Resampling-stable lineage with downstream benefit

**Question:** Can correspondence survive Gaussian split/merge/prune/densify/retraining and improve editing or change reasoning?

**Why it survives:** generic persistent IDs are occupied, but representation-resampling identity is still a concrete failure mode.

**Hard gate:** must beat nearest-neighbor/covariance/ICP/OT correspondence and materially improve a downstream task. Identity accuracy alone is insufficient.

## S5 — Observability/contradiction evidence for deletion and resurrection

**Question:** Can explicit support, contradiction, observability and age reduce false deletion under occlusion while reacting faster to true removals/reappearances?

**Why it survives:** it can plug into persistent world history and has a direct falsifiable temporal benchmark.

**Hard gate:** beat visibility-only and simple temporal-threshold baselines on false deletion, stale-geometry lifetime and identity churn.

## S6 — Change-causal repair routing

**Question:** Can geometry/material/lighting/semantic-only changes be routed to distinct dependency closures so unaffected representation layers do zero work?

**Why it survives:** change detection alone is occupied, but using change cause to prove which derived state does *not* need rebuilding is a stronger systems property.

**Hard gate:** lower work with output equivalence; routing mistakes must be explicitly counted.

## S7 — Compact persistent spatial dependency index

**Question:** What index structure makes world-local Gaussian selection truly local without unacceptable memory/update overhead?

**Why it survives:** hash and flat-layout probes already expose a real systems tradeoff. This is likely a component of S1, not a paper alone.

**Hard gate:** exact selection semantics; incremental maintenance; bounded bytes/primitive; M2 Pro improvement.

## S8 — Repeated-edit hidden drift as a failure regime

**Question:** Do individually acceptable local edits accumulate persistent geometry damage that ordinary render metrics fail to reveal?

**Why it survives:** it can reveal a fundamental failure mode and directly motivates S2/UWD if the effect is real.

**Hard gate:** demonstrate reproducible cumulative geometry drift under controlled edit chains, not just visible quality degradation.

## Explicitly demoted

- Raw Gaussian-field spectral phase: **rejected**.
- Canonical center-field phase: **supporting hypothesis only** until it beats simpler correspondence-free geometry baselines.
- Generic local Gaussian update: **not novel enough**.
- Generic bounded-compute continual Gaussian scheduler: **not novel enough** after EliGSiR.
- Generic persistent IDs: **not novel enough**.
- Generic mesh+Gaussian hybrid: **not novel enough**.

## Promotion rule

Only 2–4 of S1–S8 may become finalists. Promotion requires: direct closest-prior-art comparison, held-out evidence, novel-component ablation, and a result that cannot be explained by a simpler mechanism.
