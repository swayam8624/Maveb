# Paged stable atlas dirty-granularity probe v2

**Evidence class:** synthetic dependency-granularity kill probe.  
**Not:** texture quality, GPU timing, or a novelty claim.

The fixed-global stable atlas preserved UV addresses but failed capacity scaling. The next obvious
idea is paged stable addressing. This probe asks a narrower question:

> If a page is the unit of upload/invalidation, does stable paging keep a sparse patch update sparse?

For 250,000 active stable slots, the experiment changes 0.1%, 1%, or 5% of slots. It compares
randomly scattered changes with one contiguous cluster. Unchanged stable addresses survive by
construction in both cases.

| slots/page | changed | random dirty pages (mean) | clustered dirty pages | ideal sub-page writes |
|---:|---:|---:|---:|---:|
| 64 | 0.1% | 6.20% | 0.128% | 0.1% |
| 64 | 1% | 47.35% | 1.024% | 1% |
| 64 | 5% | 96.22% | 5.017% | 5% |
| 256 | 0.1% | 22.67% | 0.205% | 0.1% |
| 256 | 1% | 92.13% | 1.126% | 1% |
| 256 | 5% | 100% | 5.118% | 5% |
| 1024 | 0.1% | 64.37% | 0.408% | 0.1% |
| 1024 | 1% | 99.92% | 1.224% | 1% |
| 1024 | 5% | 100% | 5.306% | 5% |
| 4096 | 0.1% | 96.77% | 1.613% | 0.1% |
| 4096 | 1% | 99.68% | 1.613% | 1% |
| 4096 | 5% | 100% | 6.452% | 5% |

Source: `research/probes/paged_atlas_dirty_granularity_v2.py`,
commit `a68f1c9fd0ba38a1f943fa7a4dfdb37b13f6bb00`,
blob `13f9d62548ae89955d94abddf876afb04d5c4a39`.

Runtime: Python 3.13.5, NumPy 2.3.5, Linux x86_64. The result is combinatorial/dependency evidence,
not hardware performance evidence.

## Interpretation

**Naive page-level locality is rejected.**

Stable addresses solve address churn, but if changed patches are scattered across page membership,
even a tiny changed fraction can invalidate most pages. The failure becomes dramatic as page size
grows. Therefore the S1 texture solution cannot simply be "put stable patch IDs into pages."

Two mechanisms remain plausible:

1. **spatial/dependency-coherent allocation**: patches likely to change together share pages, so
   world-local changes remain page-local;
2. **sub-page/tile writes**: the page is an address/residency unit but not the rewrite unit.

The clustered rows show the target behavior: dirty-page fraction tracks changed fraction closely
when allocation preserves locality.

## Next falsification experiment

Compare:
- random/free-list stable allocation;
- RegionKey/Morton-local allocation;
- graph-partitioned allocation using mesh adjacency/dependency;
- sub-page dirty rectangles.

Measure address survival, dirty bytes, page count, fragmentation, migration/compaction churn, and
lookup cost over repeated real edit sequences.

## Decision

**Kill naive paged atlas; promote locality-preserving page assignment/sub-page writes as the only
texture variant worth implementing.** This remains infrastructure for S1, not standalone novelty.
