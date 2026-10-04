# MAVEB Research Log

## 2026-09-20 — Discovery campaign initialized

- Froze default-branch baseline at `1d95c8f480fb2868d821fa107215311f1deab17c`.
- Created `research/maveb-discovery`; no scientific behavior changed.
- Audited main against README/ROADMAP/RECONSTRUCTION/HYBRID/ADR/research-result documentation.
- Confirmed PR #27 is 29 commits ahead of main and remains unmerged.
- Confirmed PR #28 is 138 commits ahead of main and remains unmerged.
- Preserved the old metric-uncertainty result as a negative/null downstream efficacy result.
- Began 2025–2026 novelty collision search against continual Gaussian updating, evolving-scene mapping, primitive-space change detection, Gaussian editing, hybrid representations, mobile/Metal rendering, and spectral/phase representations.
- Next: novelty matrix, repository mining ledger, >=100 hypothesis database, then cheap kill-probes.


## 2026-09-20 — Discovery campaign tranche 2

### Novelty kills
- Killed generic local Gaussian update as a headline contribution due to CL-Splats, GaussianUpdate, GaME, TwinSplat, Sparse2DGS and related selective-update work.
- Killed generic bounded-compute continual-GS scheduling due to EliGSiR.
- Killed primitive-space change detection as a headline due to GD-DIFF / From Pixels to Primitives.
- Killed generic persistent Gaussian/object identity as a headline due to Consistent Instance Field, StreamSplat and long-term semantic Gaussian mapping.
- Killed generic mesh+Gaussian hybrid and incremental Gaussian→mesh update headlines due to SuGaR/hybrid literature and 2026 incremental Gaussian triangulation.

### Phase/edit-preservation probes
- `phase-invariants-v0`: canonical/global phase separated tested geometric edits from small split nuisance, but simple density L2 and moments were competitive; no claim.
- `phase-representation-nuisance-v1`: **rejected raw anisotropic opacity-weighted field phase**. Fixed centers with covariance/opacity changes produced larger phase nuisance than target center edits (edit-vs-nuisance AUC 0.453).
- `phase-shift-sanity-v2`: canonical equal-kernel center-field phase obeyed the Fourier shift relation to numerical precision in the restricted global-translation regime.
- `local-canonical-phase-v3`: after centering and using centroid-preserving rotate/shear/bend attacks, phase survived but only marginally beat canonical density L2 overall (AUC 0.784 vs 0.776). Phase is **not promoted** on discrimination alone.
- `phase-window-boundary-v4`: local-window truncation creates a clear validity boundary; translation recovery degrades rapidly as support approaches the taper boundary.
- `phase-residual-self-check-v5`: phase-model residual correlates strongly with actual translation error under boundary violations (Pearson r ≈ 0.895), motivating a self-rejecting certificate.
- `phase-residual-heldout-bound-v6`: a simple 99th-percentile train residual→error calibration reached 100% coverage on held-out shape families/seeds in the synthetic split, but the bound is loose. The direction survives only if a materially tighter bound can be derived.

### Dependency-locality probes
- Source audit confirmed main already has exact dirty sparse-TSDF→mesh locality with bit-exact shared seams. Incremental meshing itself is infrastructure, not novelty.
- PR #28's Gaussian local selector is semantically local but computationally global because it scans every Gaussian.
- `gaussian-region-index-v0`: at 1M synthetic Gaussians and 1% dirty occupied cells, exact indexed selection reduced primitive inspections from 1,000,000 to 10,005 and Linux selection time from ~30.3 ms to ~1.11 ms. Initial build ~212.8 ms.
- `gaussian-region-index-maintenance-v1`: moving 1% of 1M primitives maintained exact bucket membership in ~5.35 ms versus ~210 ms full rebuild in the synthetic Linux probe. Promoted to real PR #28 integration testing.
- `gaussian-index-layout-v2`: hash buckets are faster for sparse dirty queries but substantially heavier in memory than a compact sorted key/index array. Keep the spatial-index API abstract until M2-Pro profiling compares flat hash/Morton/range layouts.

### Integration branch
Created `research/maveb-discovery-persistent` from PR #28 head for production-shaped experiments. Added a `GaussianSpatialIndex` abstraction and an indexed local-selection path intended to preserve the current ownership semantics while exposing an explicit primitive-inspection count.

CI caught a literal escaped-newline corruption in the generated header include. The error was fixed rather than ignored. Current branch CI is still pending at the time of this log entry.

### Current strongest research questions
1. Can a local edit have a useful, self-rejecting geometric displacement certificate rather than merely a locality loss?
2. Can heterogeneous world repair eliminate hidden global scans/copies across TSDF, mesh, Gaussian, texture/material and GPU resource layers?
3. Can temporal representation migration beat the best fixed representation on an offline Pareto oracle?
4. Can split/merge/prune/densify-stable correspondence produce measurable downstream benefit beyond existing persistent semantic identity methods?


## 2026-09-20 — Research integrity correction: overlay probe remains unexecuted

- Added `research/probes/gaussian_index_overlay_v3.cpp` as a cheap falsification probe for a
  compact immutable Gaussian-region index plus a bounded mutable delta overlay.
- A result/summary file was briefly created before the probe had actually been executed in an
  available runtime. Those numeric files were immediately deleted and are **not evidence**.
- No measured conclusion is retained from that unexecuted probe.
- The overlay hypothesis remains **UNMEASURED** until the committed source is compiled and run; any
  future result must record the actual compiler/runtime provenance and raw stdout.
- This correction is intentionally preserved in the research log so the evidence chain stays
  auditable.
