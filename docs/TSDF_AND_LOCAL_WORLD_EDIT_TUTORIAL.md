# Maveb — from captured depth to a selective world revision

> **Restored from a November 21, 2026 teaching branch.** Check links and algorithm statements against current source before using this as verification evidence. This tutorial documents intended contracts, not a newly executed test.

This tutorial is an implementation-oriented companion to [SOURCE_READING_ORDER.md](SOURCE_READING_ORDER.md), not a substitute for reading the source or running its tests. It separates three questions that are often mixed together: **What can the sensor observe? What geometry does the fusion system infer? Which part of a persistent world must change after an edit?**

## 1. The three coordinates you must keep distinct

A depth sensor yields pixel coordinates `(u, v)` and a measured depth `d`. Camera intrinsics, such as `fx, fy, cx, cy`, convert that measurement into a camera-space point. A calibrated camera-to-world orientation/translation converts the point into the shared world frame. Finally, the TSDF uses an origin, voxel size, and logical grid dimensions to locate its discrete samples.

The implementation in [SparseTsdfVolume.cpp](../engine/reconstruction/src/SparseTsdfVolume.cpp) applies these transforms to select candidate blocks and project voxel samples into depth frames. Its [configuration contract](../engine/reconstruction/include/aether/reconstruction/SparseTsdfVolume.hpp) includes voxel spacing, truncation distance, minimum/maximum usable depth, a maximum voxel weight, and explicit resident-block budgets.

Never treat an image pixel, a metric 3D point, and a voxel/block index as interchangeable coordinates. Many apparent reconstruction errors are coordinate-frame or unit mistakes rather than meshing bugs.

**Exercise:** pick one calibrated camera pixel and write the complete chain: pixel/depth → camera coordinates → world coordinates → voxel index → sparse block/local index. Identify which steps require a rotation inverse.

## 2. What a truncated signed distance stores

Each volume voxel keeps a signed-distance value, a weight, color and an observation count. A TSDF does not simply mark a pixel as occupied. A sample represents how far a voxel lies in front of or behind an observed surface **along the camera's depth direction**, clipped by the configured truncation band.

In [`SparseTsdfVolume::integrate`](../engine/reconstruction/src/SparseTsdfVolume.cpp), the relevant calculation is:

[
d_{s} = d_{	ext{observed}} - z_{	ext{projected}}, qquad
hat d = operatorname{clamp}(d_s / mu,,-1,,1)
]

Here (mu) is the truncation distance. The source rejects invalid depths and confidence values, ignores voxels too far behind the observed surface, then computes a sample weight from depth confidence multiplied by pose confidence. It updates distances and colors by a weighted average and caps accumulated weight at `maximumWeight`.

As a consequence, a voxel with allocated storage but **zero observation weight** is not equivalent to an observed free-space voxel. Likewise, confidence weighting is not a guarantee that an inaccurate camera pose has been corrected; it controls how strongly the measurement influences fusion.

The volume validates its configuration in `SparseTsdfVolume::create`: block resolution is power-of-two and in the bounded range, dimensions and physical extents must be valid, truncation cannot be smaller than voxel spacing, and the maximum allocated payload is capped.

## 3. Why sparse allocation is a separate algorithm

[`candidateBlocks`](../engine/reconstruction/src/SparseTsdfVolume.cpp) does not integrate density values. First it uses camera rays and the depth/truncation neighborhood to determine which sparse blocks might need updates. It rejects invalid observations and footprints that exceed its configured limits. Only then does `integrate` inspect candidate blocks, copy existing payloads into a temporary update set, compute changed voxel values, and commit the results.

This separation matters for both **performance** and **correctness**. A naive full dense grid wastes memory on unobserved regions. An unbounded sparse insertion scheme may still exhaust memory catastrophically if one badly calibrated frame traverses a huge region. Candidate and resident-block budgets are therefore part of the API contract, not implementation trivia.

[`statistics`](../engine/reconstruction/src/SparseTsdfVolume.cpp) reports resident blocks, observed voxels, last-frame updates and dirty-block counts. Treat these as work/memory counters, not measurements of geometric accuracy.

**Exercise:** record the number of candidate blocks, newly allocated blocks, observed voxel updates and extraction voxels for two camera poses of the same scene. Ask whether a difference is caused by view coverage, ray footprint or a correctness problem.

## 4. Extracting an actual surface

[`SparseTsdfVolume::extractMesh`](../engine/reconstruction/src/SparseTsdfVolume.cpp) needs observed TSDF data. It computes a bounded region spanning resident blocks, materializes the required voxel samples for its mesh extraction path, and returns a `mesh::MeshAsset`. Its extraction memory budget is distinct from the resident sparse block budget.

The key distinction: a TSDF is a scalar field; a triangle mesh is a surface representation produced from that field. Extracting triangles does not prove that the triangles accurately match a capture, nor that a subsequent local repair is seamless. Compare against [IncrementalSparseTsdfMesher](../engine/reconstruction/src/IncrementalSparseTsdfMesher.cpp) and [ReferenceMarchingCubes](../engine/reconstruction/src/ReferenceMarchingCubes.cpp) to understand local versus reference extraction.

**Exercise:** create one simple synthetic plane or sphere with known geometry, then measure surface displacement/error under different voxel sizes and truncation distances. Record memory and elapsed work separately from geometric quality.

## 5. A scene entity is not a permanent GPU object

[Scene.cpp](../engine/scene/src/Scene.cpp) manages entity slots with generations, names, transforms and parent relationships. A stale `Entity{index, generation}` must fail validation after a slot is reused. `setParent` prevents cycles; `setLocalTransform` rejects nonfinite transforms/zero scale; world matrices are lazily cached and invalidated through descendants when a parent or transform changes.

The [SwiftUI viewport](../apps/AetherStudio/Sources/AetherViewport.swift) collects user edits, tracks selected entities and caches last-applied UI values through its Coordinator. The [Objective-C++ bridge](../apps/AetherStudio/Bridge/AetherViewportBridge.mm) translates them to native C++/Metal calls. [Renderer.cpp](../engine/metal/src/Renderer.cpp) owns the actual GPU pipelines, command queue, frame contexts and render resources.

When `Renderer::uploadPrivateBuffer` copies data to private GPU memory, its shared staging buffer must remain alive until the asynchronous blit completes. When the renderer is destroyed, it waits for its in-flight frame slots. A SwiftUI selection binding is therefore **not** a Metal buffer owner, and a persistent scene ID is **not** a GPU resource handle.

## 6. Preparing a persistent world edit is not committing it

[WorldEdit.cpp](../engine/world/src/WorldEdit.cpp) implements `prepareWorldEdit(previous, timestamp, patches, policy)`. It starts by validating the old snapshot and a monotonically newer timestamp; it rejects duplicate IDs, references to missing entities, contradictory removal patches and changes that have no effect.

One subtle, important invariant: a translation-only transform can shift an existing axis-aligned world bound by the translation delta. A rotation or scale change cannot safely reuse that bound, so the patch must explicitly provide updated world bounds. Silently retaining old bounds would break spatial locality and selective-update decisions.

The function produces **three distinct outputs**: a candidate next-revision world, a semantic diff from the previous world, and a selective-update plan. It does not silently commit the candidate to a global database. The caller can inspect the proposed change and its effect on unaffected regions before advancing persistent state.

Follow [PersistentWorld](../engine/world/include/aether/world/PersistentWorld.hpp), [LocalityLedger](../engine/world/include/aether/world/LocalityLedger.hpp), and [CBRC revision graph](../engine/cbrc/include/aether/cbrc/CapturedWorldRevisionGraph.hpp) to see how locality evidence and provenance are intended to survive individual edits.

**Exercise:** prepare an edit that translates one entity, then another that rotates it. Show why the second must supply replacement bounds. Compare the output diff and selective-update plan; list every unaffected entity or representation you would expect to remain unchanged.

## 7. What tests must prove

There are separate proof obligations, and passing one does not imply the others:

- **Numerical:** fused voxel values, coordinate transforms and observed weights match a CPU/reference oracle within defined tolerances.
- **Geometric:** the reconstructed surface matches a known synthetic model or independently measured scene.
- **Locality:** editing one region does not silently mutate the appearance/geometry of unrelated regions.
- **GPU:** Metal execution matches the intended CPU/reference path within controlled precision and backend conditions.
- **Reproducibility:** every experiment records its dataset, split, sensor calibration, seed, config, source revision and measured metric.

Start with [tests](../tests/), [benchmarking](BENCHMARKING.md), [evidence rules](EVIDENCE.md), and [CBRC research](research/CBRC.md). An attractive screenshot is not a substitute for measured locality or reconstruction error. These source comments and equations are a **learning guide**; only the tests/recorded evidence can establish a research claim.
