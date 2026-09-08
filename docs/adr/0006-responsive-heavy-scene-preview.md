# ADR 0006: Responsive Heavy-Scene Preview

- Status: Proposed
- Date: 2026-09-08

## Context

Captured `.aether` worlds can contain hundreds of thousands or millions of Gaussian splats. The
current standard GPU path projects splats, computes covariance, counts tile overlap, builds and sorts
tile/depth keys, constructs tile ranges and composites every frame. Treating the Studio viewport as
a full-quality render therefore makes navigation and scene import unusable on sufficiently large
captures even when the canonical asset itself is valid.

AetherStudio also previously loaded scene assets synchronously into the renderer owned by the
MTKView delegate. Large package decode, Gaussian conversion and Metal allocation could therefore
block the main UI path.

## Decision

AetherStudio gets a distinct responsive preview policy while the canonical renderer/package formats
remain unchanged.

### Interaction quality

During camera/object interaction the Studio reduces drawable resolution and bounds the number of
Gaussians submitted to the projection/sort/composite path. The budget is motion-sensitive and
recovers progressively after input settles instead of jumping directly to maximum density.

### Early projection rejection

The Studio projection shader performs conservative depth, opacity, coarse screen-bound and
sub-pixel rejection before exact covariance and spherical-harmonic evaluation. The correctness
shader remains available for reference and non-preview validation paths.

### Spatially progressive ordering

Large Gaussian assets are converted into a deterministic coarse spatial ordering before upload. A
32x32x32 grid groups splats by world-space position. The uploaded order is produced by round-robin
sampling occupied cells, so every low-budget prefix covers the scene broadly instead of selecting an
arbitrary contiguous prefix from trainer/package order.

The operation is linear in asset size and intentionally avoids an N log N sort on the import path.
Canonical source indices are preserved bit-exactly in an otherwise-unused GPU field so picking and
ID/debug output can still refer to the original Gaussian identity.

Small assets remain in canonical order to keep tiny correctness fixtures stable.

### Isolated asynchronous scene loading

Heavy scene import constructs a fresh renderer on a dedicated serial worker queue. Decode, package
read, Gaussian conversion, spatial ordering and Metal resource creation occur against that isolated
renderer, not the renderer currently used by the MTKView.

Once the candidate renderer has loaded successfully, the bridge swaps it with the active renderer
under a narrow renderer-swap lock. Camera/exposure state is preserved, editor state is reapplied, and
the retired renderer is destroyed off the main thread after its in-flight command buffers drain.
Failed or stale loads never replace the active renderer.

## Consequences

- Heavy imports no longer need to block the macOS UI while mutating the active renderer.
- Navigation cost is bounded and low-budget previews represent the whole scene more evenly.
- Still quality can recover after motion without modifying the source `.aether` asset.
- The preview remains approximate; this is not yet a true hierarchical visibility/LOD structure.
- A future production path should replace the coarse grid/prefix mechanism with GPU-driven spatial
  hierarchy traversal, frustum/importance selection and workload control from measured frame time.

## Non-goals

This ADR does not change reconstruction output, package semantics, the canonical Gaussian codec, or
release-quality rendering claims. It is an editor responsiveness policy and an intermediate step
toward hierarchical Gaussian LOD.
