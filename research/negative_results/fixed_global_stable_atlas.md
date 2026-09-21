# Fixed global stable atlas does not scale to large persistent worlds

**Date:** 2026-09-20
**Status:** rejected as a large-world production architecture; retained as a small/medium correctness fixture.

## Hypothesis

A single fixed-capacity texture atlas could give persistent mesh triangles/patches stable UV addresses
across local insertions, removals and reorderings, eliminating the current ordinal-atlas global UV
churn.

## Implementation / probe

The `research/maveb-stable-atlas` branch implements a deterministic fixed-capacity
`StableTextureAtlasLayout`. The discovery campaign then ran
`research/probes/stable_atlas_capacity_v1.py` for an 8192×8192 atlas with a 4-pixel gutter.

The probe is analytical: it evaluates address capacity and nominal per-slot texel budget. It does not
claim rendered quality.

## Result

Stable addresses are possible, but globally reserving capacity collapses tile resolution as the
persistent world grows:

- 10,000 reserved slots: 73-pixel inner tile.
- 100,000: 17 pixels.
- 250,000: 8 pixels.
- 500,000: 3 pixels.
- 750,000: 1 pixel and invalid under the current layout contract.
- 1,000,000: zero inner pixels.

Overprovisioning is also severe: reserving 100,000 slots for 10,000 active triangles leaves only
about 5.4% of the nominal per-triangle texel area of the active-count layout.

Raw artifact:
`research/results/probes/stable-atlas-capacity-v1.json`.

## Suspected reason

The design binds **address stability** to **global pre-allocation**. Capacity increases therefore
divide one finite atlas among ever more persistent slots, even when most capacity is inactive or
historical.

## Decision

**Permanently reject the single globally fixed-capacity atlas as the scalable S1 texture solution.**

Do **not** reject stable addressing itself. The existing implementation remains useful as:

1. a correctness oracle for slot-to-UV stability;
2. a small/medium-scene fixture;
3. a baseline for the next paged/sparse/indirected design.

## Next variant

Test persistent page/tile addressing where new capacity allocates new pages without moving existing
addresses. Measure address survival, texel density, fragmentation, resident bytes, dirty-page writes,
lookup/binding overhead and compaction invalidation.
