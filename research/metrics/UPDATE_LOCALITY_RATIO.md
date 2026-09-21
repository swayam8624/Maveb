# Update Locality Ratio (ULR) Evidence Contract

**Status:** research metric specification
**Date:** 2026-09-20

## Motivation

A system can claim to be "local" while still performing hidden global work:

- scan all Gaussians to select a local subset;
- copy all resident TSDF blocks before local meshing;
- rebake every texture tile after one patch changes;
- rewrite an entire GPU Gaussian buffer after a local edit;
- serialize every historical world snapshot after one revision.

ULR is designed to make these leaks visible.

## 1. Never mix incomparable work units

There is **no single primitive-count numerator** that makes a TSDF voxel update, a Gaussian
inspection, a texture texel rewrite, and a disk byte equivalent.

Every experiment therefore reports the layer vector

[
mathbf{ULR} =
(
r_{mathrm{tsdf}},
r_{mathrm{mesh}},
r_{mathrm{gaussian}},
r_{mathrm{texture}},
r_{mathrm{gpu}},
r_{mathrm{history}}
)
]

where each component is

[
r_l = rac{W_l^{mathrm{incremental}}}{W_l^{mathrm{full}}}
]

using the *same unit within that layer*.

Examples:

- TSDF: blocks/voxels touched;
- mesh: owner patches/cells regenerated;
- Gaussian: primitives inspected and primitives rewritten;
- texture: triangles reconsidered, atlas texels rewritten;
- GPU revision: canonical bytes written / allocated;
- history: bytes appended/written.

## 2. Directly comparable end-to-end ratios

Two end-to-end quantities are legitimate because their units are shared:

[
ULR_{mathrm{latency}} =
rac{T_{mathrm{incremental}}}{T_{mathrm{full}}}
]

and

[
ULR_{mathrm{bytes}} =
rac{B_{mathrm{incremental}}}{B_{mathrm{full}}}.
]

Latency must be measured over the same transaction boundary and synchronization policy.

Bytes must name the domain being counted (CPU writes, GPU upload bytes, disk bytes, or network
bytes). Do not add unrelated byte domains together without reporting them separately.

## 3. Correctness gates come first

A low locality ratio is meaningless if the result is wrong.

A result is eligible for a positive locality claim only when its declared correctness gates pass.
Depending on the layer these include:

- exact selected Gaussian set;
- exact TSDF/mesh triangle coverage where exactness is claimed;
- bounded floating-point surface error where bit exactness is impossible;
- identical persistent entity semantics;
- texture UV/address stability;
- equivalent rendered/geometry quality to the declared full baseline;
- exact historical revision reconstruction.

The JSON evaluator marks a run **ineligible** if any required correctness gate fails.

## 4. Changed-world fraction is not ULR

The independent variable

[
c = rac{	ext{changed spatial/world support}}{	ext{total support}}
]

must be reported separately.

The core scaling experiment asks whether

[
ULR(c) approx O(c)
]

for small (c), rather than tending toward one because of hidden global scans/copies.

At minimum test:

[
cin{0.1%,0.25%,0.5%,1%,2%,5%,10%,25%,50%,100%}.
]

## 5. Required baselines

Each run must compare against:

1. full rebuild/reload;
2. current MAVEB implementation;
3. simple local baseline if one exists;
4. novel dependency mechanism;
5. ablation disabling the novel dependency metadata/index.

## 6. Required evidence fields

Every run records:

- exact repo SHA and branch;
- machine/OS/backend;
- scene/dataset/revision IDs;
- changed fraction and changed-region definition;
- full and incremental counters for every available layer;
- full and incremental end-to-end latency;
- byte domains separately;
- quality/correctness gates;
- peak memory;
- warmup/repetition/statistical protocol.

## 7. Paper-level success condition

A systems contribution requires more than one fast microbenchmark.

The useful claim is:

> Across held-out revision sequences and multiple scene scales, the dependency-driven path preserves
> the declared full-rebuild quality/correctness while revision work scales with the affected
> dependency closure instead of total world size.

Failure on a layer is retained as evidence. A layer that remains globally coupled must be shown
explicitly rather than omitted from the ULR vector.
