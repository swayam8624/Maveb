# Dependency Locality Audit v1 — GPU/Temporal Leaks

The deeper source audit found that PR #28's local Gaussian mutation is only partially local.

## 1. Selection

The original selector scans all Gaussian primitives. The new experiment branch is testing a persistent RegionKey index to replace this O(N) scan.

## 2. Publication barrier

`Renderer::translateGaussians` constructs `FrameQuiescence`, which acquires **every renderer frame slot** before touching the shared Gaussian source buffer.

This is safe, but it makes publication globally synchronized:

```
tiny local edit
   ↓
wait for every in-flight frame
   ↓
block new frame submission
   ↓
mutate a few Gaussian records
```

A future minimal-work system must measure this stall explicitly. Candidate mechanisms include versioned/double-buffered regional pages, deferred GPU patch commands, or copy-on-write chunks.

## 3. Temporal history

After any Gaussian translation the renderer executes:

```cpp
temporalHistoryValid_ = false;
```

So a local edit invalidates temporal history for the **whole frame**.

That creates a new research target: spatially/versioned temporal invalidation. A dirty edit should invalidate only screen-space history whose world support changed, provided the dependency can be proven safe.

## 4. Sparse TSDF transfer

The existing incremental mesher is spatially local, but the documented Metal snapshot path still copies all resident blocks to CPU. This is another hidden global transfer boundary.

## Consequence

The S1 hypothesis is now more precise:

> An update is computationally local only if selection, data transfer, derived-state rebuild, GPU publication, and temporal invalidation all scale with the changed dependency closure.

A low Gaussian count in the optimizer is not enough.

These are source-audit findings, not timing claims.
