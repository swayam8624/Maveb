# Sparse TSDF contract

`SparseTsdfVolume` is AETHER's deterministic CPU reference for a block-sparse metric TSDF. It is
not a serialized file format. `SparseMetalTsdfVolume` is the fixture-level Metal 3 implementation
of the same fusion equations. The contract exists so GPU fusion, incremental meshing, persistence,
and eviction can be compared against one precise implementation rather than visual similarity.

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

Resident blocks and dirty coordinates use lexicographic `(x, y, z)` ordering. The CPU reference
stores that order directly. The Metal path gives each coordinate a stable host-assigned slot and
publishes snapshots in coordinate order. A future GPU hash lookup may change the internal search,
but externally observed allocation, fusion, and extraction results must remain deterministic for
identical inputs and configuration.

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

The Metal implementation adds independent frame-pixel, resident-byte, and per-frame scratch-byte
limits. Candidate voxels are classified before resident slots are committed. Accepted blocks are
initialized or copied into private scratch storage, fused there, and published to resident storage
only after the command succeeds. A completed generation can be copied into an immutable CPU
snapshot without exposing or racing the live resource.

## Incremental extraction

Full extraction finds the allocated block AABB, checks its voxel count against the extraction budget,
copies that span into a dense scalar field, and invokes the same resolved extractor verified by the
R1 Marching Cubes suite. This proves exact topology parity without inventing a second mesher.

`IncrementalSparseTsdfMesher` consumes immutable completed-generation snapshots. Each patch owns
the cells whose minimum corner lies in one sparse block. It reads a positive topology halo and a
symmetric gradient halo, so adjacent patches emit each cell once while shared positions and normals
remain bit-exact. A changed block invalidates itself and the seven negative neighbours whose cells
can reference its samples. Updates explicitly replace or remove cached patches and stale generations
are rejected transactionally.

Patch extraction is currently CPU work over a snapshot. R5 remains open for selective Metal
readback, GPU-resident Marching Cubes, persistence/eviction, asynchronous scheduling, real-capture
agreement, and throughput/soak evidence.

## Evidence

`AetherSparseTsdfTests` proves exact dense/sparse voxel and resolved-mesh agreement under a
translated and yaw-rotated camera, deterministic repeated runs, ordered dirty blocks, bounded
hostile inputs, transactional failures, and local allocation inside a billion-voxel logical room.
The generated JSON must byte-match
`benchmarks/evidence/r5-sparse-cpu-m2-pro-2026-08-12.json` during CTest.

`AetherSparseMetalTsdfTests` runs the same translated/yaw-rotated frame through independent Metal
volumes and the CPU reference, repeats fusion through weight saturation, compares every resident
voxel, proves completed-generation snapshot isolation and dirty-block parity, and exercises block,
frame-pixel, resident-byte, and scratch-byte failures. The M2 Pro fixture report is committed at
`benchmarks/evidence/r5-sparse-metal-m2-pro-2026-08-13.json`. It is E2 evidence only; its
synchronous wall time is intentionally not recorded as a performance claim.

The incremental fixture processes 106 dirty blocks into 120 replacement/removal updates and 30
resident surface patches. Those patches contain exactly the full extractor's 1,680 triangles, with
bit-exact shared positions and normals. The raw report is
`benchmarks/evidence/r5-incremental-meshing-m2-pro-2026-08-13.json`.
