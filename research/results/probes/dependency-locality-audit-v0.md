# Dependency Locality Audit v0

**Date:** 2026-09-20  
**Type:** source/evidence audit, not a fresh timing benchmark  
**Main baseline:** `1d95c8f480fb2868d821fa107215311f1deab17c`  
**PR #28 head:** `f157b2a40e2766bcb02d24ca055073e866140476`

## What is already solved internally

MAVEB's main branch already contains a deterministic incremental sparse-TSDF mesher. Dirty blocks expand to the exact neighbouring cell owners that can depend on them; topology and gradient halos preserve shared boundaries. The committed E2 fixture reports **106 dirty blocks → 120 patch updates → 30 resident patches**, with **1,680 incremental triangles = 1,680 full-extraction triangles**, exact triangle coverage, and bit-exact shared positions/normals.

Therefore **"incremental TSDF meshing" is not our research contribution**. It is infrastructure.

## Where locality currently leaks

PR #28 introduces a useful chain:

```
Reality Diff
   ↓
dirty metric RegionKeys
   ↓
Gaussian ownership-aware local selection
```

But `selectGaussiansForLocalUpdate` still loops over every Gaussian in the asset, computes its region key, and probes the dirty-region table. For an N-Gaussian world, selecting a tiny changed region is still an **O(N) primitive scan**.

Likewise, the current Metal sparse-TSDF path exposes immutable snapshots but the documented implementation still copies all resident blocks before CPU patch extraction. The downstream mesher is local; the transfer boundary is not.

This is the exact distinction we must preserve:

> **semantic locality is not the same thing as computational locality.**

A paper-worthy minimum-work claim cannot hide full-scene scans, copies, or rebuilds behind a small dirty-region set.

## Novelty decision

Generic local updating is already occupied by continual-GS and evolving-scene methods. We therefore **kill "local update" as a headline contribution**.

The surviving question is narrower and stronger:

> Can an observation/change transaction compute and execute the minimal affected dependency closure across heterogeneous state—TSDF blocks, mesh patches, Gaussian clusters, textures/materials, and render resources—while matching the full-rebuild result?

That claim only becomes interesting if work scales with the changed dependency closure rather than total world size.

## Immediate falsification probe

Build a RegionKey→Gaussian index on the PR #28 branch and compare it against the current full scan for 10K–1M Gaussians and 1%–50% changed-world fractions.

Record exact selection equivalence, primitive inspections, index build/update work, memory overhead, and later Apple-silicon wall time.

If the index/maintenance overhead erases the advantage, stop. If this tiny component works, it still does **not** prove the paper; it only removes one hidden O(N) leak before cross-layer ULR can be tested.
