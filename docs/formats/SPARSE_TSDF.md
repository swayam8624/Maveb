# Sparse CPU TSDF contract

`SparseTsdfVolume` is AETHER's deterministic CPU reference for a block-sparse metric TSDF. It is
not a serialized file format and is not yet the live Metal backend. The contract exists so future
GPU allocation, incremental meshing, persistence, and eviction can be compared against one precise
implementation rather than against visual similarity.

## Logical and resident coordinates

The logical volume uses the same world-space definition as `DenseTsdfVolume`:

```text
world(x, y, z) = originMetres + voxelSizeMetres * (x, y, z)
```

Camera coordinates use `+Z` forward. Dimensions describe the logical voxel domain and do not imply
allocation. Each resident block contains `blockResolution cubed` `TsdfVoxel` records; supported
block resolutions are powers of two from 2 through 32. Block `(bx, by, bz)` owns logical voxel
`(bx * B + lx, by * B + ly, bz * B + lz)`. Partial blocks at the positive volume boundary retain
storage for a complete block, but out-of-domain samples are never fused or extracted.

Resident blocks and dirty coordinates use lexicographic `(x, y, z)` ordering. This ordered CPU
representation favors reproducibility over hash-table throughput. A production Metal backend may
use hashing internally, but externally observed allocation, fusion, and extraction results must
remain deterministic for identical inputs and configuration.

## Candidate allocation and fusion

For every accepted depth pixel, fusion clips the metric camera ray to the logical block AABB and
traverses it from `minimumDepthMetres` through `observedDepth + truncationDistanceMetres`. The
traversed cells are conservatively inflated by the projected half-pixel footprint. Rays that do not
intersect the logical volume allocate nothing; non-finite or unrepresentable footprints fail.

Only the resulting candidate blocks are evaluated. Each candidate voxel uses the dense oracle's
nearest-pixel projection and exact confidence, normalized signed-distance, weight-saturation,
observation-count, and color equations. Candidate blocks are copied into a temporary ordered map
and committed only after the complete frame succeeds. Invalid input, candidate-budget exhaustion,
resident-budget exhaustion, or an internal traversal failure leaves all resident blocks and
statistics unchanged.

## Explicit budgets

- `maximumCandidateBlocksPerFrame` bounds ray expansion before voxel evaluation.
- `maximumBlocks` bounds resident voxel payload; creation also rejects configurations exceeding
  256 million resident samples.
- `maximumExtractionVoxels` bounds the dense active-span snapshot and cannot exceed 64 million.

Statistics distinguish logical extent from actual allocation: resident blocks/voxels, observed
voxels, payload bytes, integrated frames, last-frame candidates/updates, and dirty blocks are
reported independently. `clearDirtyBlocks()` is an explicit acknowledgement and never alters the
volume.

## Extraction and current limitation

Extraction finds the allocated block AABB, checks its voxel count against the extraction budget,
copies that span into a dense scalar field, and invokes the same resolved extractor verified by the
R1 Marching Cubes suite. This proves exact topology parity without inventing a second mesher.

It is deliberately not scalable incremental meshing. R5 remains open until dirty blocks can be
meshed with consistent one-block halos, extraction/rendering are snapshot-isolated, blocks can be
persisted and evicted under memory pressure, and the Metal backend agrees with both CPU references
on fixtures and real captures.

## Evidence

`AetherSparseTsdfTests` proves exact dense/sparse voxel and resolved-mesh agreement under a
translated and yaw-rotated camera, deterministic repeated runs, ordered dirty blocks, bounded
hostile inputs, transactional failures, and local allocation inside a billion-voxel logical room.
The generated JSON must byte-match
`benchmarks/evidence/r5-sparse-cpu-m2-pro-2026-08-12.json` during CTest.
