# Spatially coherent stable texture page allocation probe v3

**Evidence class:** synthetic dependency-allocation probe.  
**Not:** rendered texture quality, production allocator behavior, GPU timing, or a standalone novelty claim.

The previous paged-atlas probe rejected random/free-list whole-page updates because sparse changes
could dirty nearly the whole atlas. This probe asks whether a simple persistent **Morton ordering of
3D RegionKey-like patch coordinates** preserves enough dependency locality to make whole-page writes
plausible for spatially compact edits.

The world contains 64³ = 262,144 persistent patch slots. Twenty spatial cube positions are sampled
for three edit sizes. Stable addresses survive 100% by construction.

| actual changed support | slots/page | Morton dirty pages mean | Morton p95 | random dirty pages mean | ideal page fraction |
|---:|---:|---:|---:|---:|---:|
| 0.0824% | 64 | 0.294% | 0.450% | 5.135% | 0.0977% |
| 0.0824% | 256 | 0.557% | 0.801% | 19.014% | 0.0977% |
| 0.0824% | 1024 | 1.270% | 1.641% | 57.383% | 0.391% |
| 0.0824% | 4096 | 3.359% | 6.563% | 97.813% | 1.563% |
| 1.0468% | 64 | 1.813% | 2.008% | 49.072% | 1.050% |
| 1.0468% | 256 | 2.925% | 3.560% | 93.394% | 1.074% |
| 1.0468% | 1024 | 4.609% | 7.031% | 100% | 1.172% |
| 1.0468% | 4096 | 9.063% | 12.5% | 100% | 1.563% |
| 5.2734% | 64 | 7.510% | 8.374% | 96.990% | 5.273% |
| 5.2734% | 256 | 9.980% | 10.938% | 100% | 5.273% |
| 5.2734% | 1024 | 13.711% | 18.750% | 100% | 5.469% |
| 5.2734% | 4096 | 19.609% | 28.828% | 100% | 6.25% |

Source: `research/probes/spatial_page_allocation_v3.py`,
commit `f4b577368ce2ddbf025b1058870bc5752d026c8c`,
blob `077c5cc581ae191ef84915c1f5bf58620c378d39`.

Runtime: Python 3.13.5, NumPy 2.3.5, Linux x86_64.

## Result

**H119 survives its cheapest kill test.**

Spatially coherent Morton assignment changes the qualitative behavior. For ~1.05% spatial support,
64-slot pages dirty ~1.81% of pages instead of ~49.1% under random allocation; 256-slot pages dirty
~2.92% instead of ~93.4%. At ~5.27% support, 64-slot pages dirty ~7.51% instead of ~97%.

The result is not perfect. Coarser pages amplify dependency scope even with Morton ordering:
~1.05% support becomes ~9.06% mean page dirtiness at 4096 slots/page. Tiny 0.082% edits also suffer
boundary amplification.

## Interpretation

Three properties must be optimized together:

1. **stable address survival**;
2. **spatial/dependency coherence of allocation**;
3. **write granularity**.

The next production-oriented candidate is therefore a bounded page size with RegionKey/Morton
assignment, plus optional sub-page dirty rectangles for boundary waste. Page size becomes an
experiment variable, not a constant.

## Falsification still required

Morton order may look favorable only because this probe uses one compact cuboid. Next attacks:
- disconnected/multiple dirty regions;
- elongated surfaces and thin walls;
- mesh adjacency vs spatial proximity;
- repeated insert/remove causing allocator holes;
- migration/compaction churn;
- real reconstructed patch distributions;
- texture quality and lookup cost.

If those destroy the locality advantage, whole-page writes are killed and only sub-page updates
survive.

## Decision

**PROMOTE H119 TO PRODUCTION-SHAPED ALLOCATOR PROBE; DO NOT CLAIM NOVELTY.**
