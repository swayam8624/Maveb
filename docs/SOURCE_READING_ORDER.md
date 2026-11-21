# Maveb: source study map

This is a **learning sequence**, not the dependency/build order. The repository contains separate application, engine, research, test, benchmark, and paper workflows. Follow the actual CMake targets and existing architectural decisions before assuming any research pipeline is the default editor path.

## Start with the product, then the contracts

1. [README](../README.md), [CMakeLists](../CMakeLists.txt), [CMakePresets](../CMakePresets.json), [CONTRIBUTING](../CONTRIBUTING.md) — supported platforms, executable targets, build options and contribution rules.
2. [Metal-native architecture](architecture/0001-metal-native-core.md) and [research separation](architecture/0002-research-separation.md) — understand why render execution and experimental evidence are separated.
3. [AetherStudioApp.swift](../apps/AetherStudio/Sources/AetherStudioApp.swift) → [ContentView.swift](../apps/AetherStudio/Sources/ContentView.swift) → [AetherViewport.swift](../apps/AetherStudio/Sources/AetherViewport.swift) — SwiftUI application and viewport.
4. [AetherViewportBridge.h](../apps/AetherStudio/Bridge/AetherViewportBridge.h) → [AetherViewportBridge.mm](../apps/AetherStudio/Bridge/AetherViewportBridge.mm) — Swift/Objective-C++ boundary into engine C++/Metal. Inspect ownership/threading of bridge objects.

## Learn the engine bottom-up

5. [core/JobSystem.hpp](../engine/core/include/aether/core/JobSystem.hpp) → [JobSystem.cpp](../engine/core/src/JobSystem.cpp), then [Diagnostics](../engine/core/include/aether/core/Diagnostics.hpp) and [Profiler](../engine/core/include/aether/core/Profiler.hpp) — scheduling and observability.
6. [scene/Transform.hpp](../engine/scene/include/aether/scene/Transform.hpp), [Camera.hpp](../engine/scene/include/aether/scene/Camera.hpp), [Scene.hpp](../engine/scene/include/aether/scene/Scene.hpp), [Lighting.hpp](../engine/scene/include/aether/scene/Lighting.hpp) — scene data passed toward rendering.
7. [mesh/MeshAsset.hpp](../engine/mesh/include/aether/mesh/MeshAsset.hpp) → [GltfLoader.cpp](../engine/mesh/src/GltfLoader.cpp) and [Animation.cpp](../engine/mesh/src/Animation.cpp) — mesh representation, glTF asset ingestion and animation.
8. [rendergraph](../engine/rendergraph/) — pass/resource scheduling; use the source CMake file to navigate implementations.
9. [metal/Renderer.hpp](../engine/metal/include/aether/metal/Renderer.hpp) → [Renderer.cpp](../engine/metal/src/Renderer.cpp) → [FrameContext.cpp](../engine/metal/src/FrameContext.cpp) — GPU render lifecycle. Compare host-side C++ logic with the Metal shaders in [shaders](../shaders/).
10. [GaussianPipeline.hpp](../engine/metal/include/aether/metal/GaussianPipeline.hpp) → [GaussianPipeline.cpp](../engine/metal/src/GaussianPipeline.cpp) — Gaussian rendering alongside the conventional mesh path. See [hybrid rendering notes](HYBRID_RENDERING.md).

## Understand captured worlds and reconstruction

11. [CapturePacket.hpp](../engine/capture/include/aether/capture/CapturePacket.hpp), [CaptureValidator.cpp](../engine/capture/src/CaptureValidator.cpp), [KeyframeSelector.cpp](../engine/capture/src/KeyframeSelector.cpp) — sensor ingestion and admission checks. Also see the [capture app](../apps/MavebCapture/Sources/MavebCaptureApp.swift).
12. [ReconstructionInput.hpp](../engine/reconstruction/include/aether/reconstruction/ReconstructionInput.hpp) and [ReconstructionContracts.hpp](../engine/reconstruction/include/aether/reconstruction/ReconstructionContracts.hpp) — research/geometry input invariants.
13. [SparseTsdfVolume.hpp](../engine/reconstruction/include/aether/reconstruction/SparseTsdfVolume.hpp), [UncertaintyTsdfVolume.hpp](../engine/reconstruction/include/aether/reconstruction/UncertaintyTsdfVolume.hpp), [IncrementalSparseTsdfMesher.hpp](../engine/reconstruction/include/aether/reconstruction/IncrementalSparseTsdfMesher.hpp) — volumetric fusion and local extraction. Cross-check [sparse TSDF format](formats/SPARSE_TSDF.md).
14. [PlyLoader.cpp](../engine/gaussian/src/PlyLoader.cpp), [GaussianUpdatePlan.cpp](../engine/gaussian/src/GaussianUpdatePlan.cpp), [ReferenceRasterizer.cpp](../engine/gaussian/src/ReferenceRasterizer.cpp) — Gaussian ingestion, updates, and reference path.
15. [WorldModel.hpp](../engine/world/include/aether/world/WorldModel.hpp), [PersistentWorld.hpp](../engine/world/include/aether/world/PersistentWorld.hpp), [WorldEdit.hpp](../engine/world/include/aether/world/WorldEdit.hpp), [LocalityLedger.hpp](../engine/world/include/aether/world/LocalityLedger.hpp) — edit-aware world state and provenance.
16. [CapturedWorldRevisionGraph.hpp](../engine/cbrc/include/aether/cbrc/CapturedWorldRevisionGraph.hpp) and [CBRC research notes](research/CBRC.md) — revision tracking and selective repair boundaries.

## Verify research claims rather than only reading descriptions

17. [Research and evaluation](RECONSTRUCTION.md), [benchmark guide](BENCHMARKING.md), [evaluation](EVALUATION.md), [evidence](EVIDENCE.md) — define baselines, metrics and evidence rules before interpreting plots.
18. [Tests](../tests/) — look for CPU/oracle correctness, Metal parity, edit/revision and TSDF validation.
19. [Benchmarks](../benchmarks/README.md), [Research workflows](../research/), and [research manuscript](../researchpaper/) — distinguish measured evidence from proposed improvements.

## Cross-file traces

**Render frame:** SwiftUI viewport → Objective-C++ bridge → C++ renderer/frame context → scene/assets → shader pipeline → presented frame.

**Captured geometry:** capture app / frame source → validation & calibration → reconstruction input → sparse/uncertainty TSDF or Gaussian asset → mesh/Gaussian renderer.

**Incremental edit:** world edit → spatial/semantic locality ledger → CBRC revision graph and update plan → affected representation → renderer update. The research claim must be checked against recorded locality/quality tests.

**GPU boundary:** `.hpp` contracts and `.mm` Objective-C++ host glue prepare device resources; `.metal` shader logic runs on the GPU. Do not conflate CPU oracles with GPU implementations.

## Exercises

1. Trace a frame from `AetherViewport` to `Renderer` without crossing into the research directory.
2. Identify which state an edit invalidates, which components persist, and how CBRC records revision evidence.
3. Trace camera calibration into TSDF voxel allocation and eventual mesh extraction.
4. Find one CPU reference-vs-Metal test and explain which invariants it can prove and which it cannot.
5. Pick an experiment and identify its exact dataset, split, seed, metric and reproducibility command.

This is a curated **first-pass spine**, not an exhaustive annotated index of all 1,000+ tracked files. Source comments are being added incrementally and should be validated against implemented call paths.


## Expanded study trail — local reconstruction and durable world edits

The following links add an implementation-oriented second pass to the architecture overview above. Each sequence starts from a user-visible or imported input, crosses an algorithmic owner, then reaches an independent check or consumer.

**Capture to geometry:** [ReconstructionWorkspace](../apps/AetherStudio/Sources/ReconstructionWorkspace.swift) → [ReconstructionInput](../engine/reconstruction/src/ReconstructionInput.cpp) (bounded camera manifest) → [SensorAlignment](../engine/reconstruction/src/SensorAlignment.cpp) → [UncertaintyTsdfVolume](../engine/reconstruction/src/UncertaintyTsdfVolume.cpp) / [SparseTsdfVolume](../engine/reconstruction/src/SparseTsdfVolume.cpp) → [IncrementalSparseTsdfMesher](../engine/reconstruction/src/IncrementalSparseTsdfMesher.cpp) → [ReferenceMarchingCubes](../engine/reconstruction/src/ReferenceMarchingCubes.cpp). Compare patch outputs against full extraction and verify that uncertainty/pose handling does not hide geometric errors.

**Geometry to appearance:** [TextureBaker](../engine/reconstruction/src/TextureBaker.cpp) projects aligned camera views onto reconstructed surfaces. [GaussianPipeline](../engine/metal/src/GaussianPipeline.cpp) provides a distinct splat-based GPU visualization path. [RendererGaussianScene](../engine/metal/src/RendererGaussianScene.cpp) must quiesce in-flight frames before replacing render resources; [FrameContext](../engine/metal/src/FrameContext.cpp) owns per-frame Metal allocations and [SparseMetalTsdfVolume](../engine/metal/src/SparseMetalTsdfVolume.cpp) owns sparse GPU TSDF resources. CPU TSDF meshing, Gaussian compositing and camera-based texture baking are not interchangeable reconstruction algorithms.

**Durable world edits:** [PersistentWorld](../engine/world/src/PersistentWorld.cpp) produces stable revisions → [SelectiveUpdate](../engine/world/src/SelectiveUpdate.cpp) selects dirty regions → [LocalityLedger](../engine/world/src/LocalityLedger.cpp) measures actual incremental/full work → [WorldArchive](../engine/world/src/WorldArchive.cpp) serializes revisions → [WorldHistoryWorkspace](../apps/AetherStudio/Sources/WorldHistoryWorkspace.swift) presents diffs. An update classified local is not automatically cheaper; compare ledger counters against a full-rebuild baseline.

**Third-party boundary:** [ReferenceMarchingCubes](../engine/reconstruction/src/ReferenceMarchingCubes.cpp) retains PoissonRecon-derived marching-cubes topology attribution under BSD-3-Clause, as documented in [THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md). The repository license does not erase this notice.

### Practical audit questions

1. Which invalid JSON/path/pose inputs are rejected before reconstruction begins?
2. When do Metal frame slots become safe to reuse for newly uploaded splat or TSDF data?
3. How can an incremental surface patch be compared with full reference marching cubes on identical voxels?
4. Which source cameras and depth tests determine a texture-bake pixel?
5. What evidence proves that only a bounded part of the world changed, and what happens if the full-work denominator is zero?
