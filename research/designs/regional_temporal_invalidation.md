# Regional Temporal History Invalidation — Experiment Design

**Date:** 2026-09-20
**Candidate:** S1 dependency-certified local repair
**Status:** design only; implementation belongs on `research/maveb-discovery-persistent`.

## Existing behavior

PR #28's local Gaussian translation currently ends with:

```cpp
temporalHistoryValid_ = false;
```

The next temporal resolve therefore rejects history for **every pixel**, even if only a tiny persistent-world region changed.

The temporal shader already performs a sequence of early rejection tests:

1. global `historyParameters.x` validity,
2. current depth,
3. motion validity,
4. previous UV bounds,
5. previous-depth consistency,
6. neighborhood color clamp / history blend.

This makes a local validity mask technically separable from the rest of TAA.

## Hypothesis

For a local world edit, preserving history outside the conservative projected support of the changed world region reduces temporal recovery damage without ghosting changed pixels.

This is **not** a rendering-quality claim yet.

## Minimal experiment

Add a full-resolution or tiled `R8Uint` history invalidation mask.

- 0 = history may be reused subject to existing depth/motion checks.
- 1 = current pixel must reject history.

The temporal resolve adds one early test immediately after global validity:

```text
if global history invalid -> current
if local invalidation mask(pixel) -> current
continue existing depth/motion validation
```

## Mask generation variants

### V0 — screen rectangle
Project the 8 corners of each dirty world AABB with the current jittered camera, take the conservative rectangle, expand by N pixels, rasterize into the mask.

### V1 — previous/current union
Project dirty bounds through both current and previous view-projection matrices and invalidate their union. This protects motion across the edit.

### V2 — proxy/Gaussian support-aware
Use visible IDs or support bounds to refine invalidation after V0/V1 prove useful. Do not build this first.

## Required controls

1. global invalidation (current behavior),
2. no invalidation,
3. V0 rectangle,
4. V1 current/previous union.

## Required measurements

- fraction of screen invalidated,
- unchanged-region absolute temporal color error,
- changed-region ghosting error,
- frames until unchanged region returns to steady-state error,
- frames until changed region becomes stable,
- GPU milliseconds for mask generation + resolve,
- bytes of history discarded conceptually,
- camera/edit magnitude,
- number/volume of dirty regions.

## Safety / correctness rule

Regional reuse is allowed only for world changes whose conservative projected support is available. Unknown/global changes fall back to full invalidation.

Lighting, IBL, target resize, scene replacement, camera discontinuities and other existing global invalidation causes remain global.

## Kill conditions

Kill the mechanism if any of these hold:

- conservative masks routinely cover most of the frame on actual MAVEB edits,
- unchanged-region quality does not improve versus global invalidation,
- changed-region ghosting becomes materially worse,
- projection/mask cost erases any temporal benefit,
- dirty support cannot be bounded safely.

## Existing opportunity probe

The synthetic AABB projection probe showed median invalidated fractions:

- 1 dirty box: 0.49%
- 16 dirty boxes: 11.64%
- 64 dirty boxes: 36.67%
- 128 dirty boxes: 54.44%

Those numbers justify an implementation probe only. They are not real-scene results.
