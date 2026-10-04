# Naive stable pages do not imply local texture writes

**Date:** 2026-09-20
**Status:** rejected as the S1 texture mechanism when whole pages are the rewrite/invalidation unit.

## Hypothesis

After rejecting one globally fixed-capacity stable atlas, use fixed stable slots grouped into pages.
Unchanged patch addresses remain stable, and only pages containing changed patches are rewritten.

## Probe

`research/probes/paged_atlas_dirty_granularity_v2.py` uses 250,000 active stable slots and changes
0.1%, 1%, or 5% of them. It compares randomly scattered changes against one contiguous cluster for
64, 256, 1024, and 4096 slots/page.

Raw artifact:
`research/results/probes/paged-atlas-dirty-granularity-v2.json`.

## Result

Address survival is 100% by construction, but page-level write locality can collapse:

- at 1% random change, 64-slot pages dirty about 47% of pages;
- 256-slot pages dirty about 92%;
- 1024-slot pages dirty essentially all pages;
- clustered 1% change stays near 1% dirty pages.

Thus address stability and update locality are separate properties.

## Reason

A page is a coarse dependency unit. Random/free-list allocation destroys spatial/change coherence, so
small world changes scatter across many pages. Increasing page size amplifies the effect.

## Decision

**Reject naive stable paging with whole-page writes.**

Continue only with:
- RegionKey/Morton/mesh-dependency-coherent page allocation; and/or
- sub-page/tile/dirty-rectangle writes where page identity is not the write granularity.

This is infrastructure for S1, not standalone novelty.
