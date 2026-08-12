# AETHER Roadmap

This roadmap is an implementation ledger, not a marketing checklist. A phase is complete only when
its exit gate is backed by tests, runtime evidence, and documentation.

## Reconstruction recovery gates

These `R` gates are the critical path for the existing Phase 4 and Phase 5 work. They do not
renumber or replace the product phases.

- [x] [E1] **R0 truth reset:** remove invented-motion tracking, luminance volume deformation,
  prebuilt geometry, silent synthetic fallback, and release-facing live controls.
- [x] [E2] **R0 data contract:** immutable capture packets, source identity, presentation/host
  timestamps, calibrated planes, optional metric depth/confidence/pose, explicit source kinds,
  structured source start/stop errors, schema-v1 recorded RGB-D playback, deterministic stepping,
  and injected failure propagation.
- [x] [E2] **R1 CPU oracle foundation:** known-pose metric-depth providers, calibrated weighted TSDF,
  bounded dense reference volume, confidence rejection, unobserved-volume rejection, shared
  cube-edge isosurface vertices, deterministic geometry metrics, and atomic validated PLY output.
- [x] [E4] **R1 extractor evidence:** a separately licensed classic Marching Cubes reference
  exhaustively validates all 256 cases; the resolved production extractor covers all 254
  non-trivial cases and a shared-face ambiguity fixture. Sphere, box, thin-wall, disconnected-
  sphere, and torus fixtures report surface error, manifold edges, components, and Euler
  characteristic in a committed reproducible raw report.
- [ ] [E3] **R1 recorded-capture accuracy gate:** the public ARKitScenes slice reports real metric
  accuracy, completeness, F-score, and normal error, but its 18.35 mm median / 29.19 mm p95 surface
  error does not meet the original 5 mm / 15 mm gate. Better source resolution and sparse fusion
  remain required; synthetic extractor evidence does not close this real-capture gate.
- [x] [E3] **R1 public RGB-D slice:** ARKitScenes trajectory/depth axes are mapped through the exact
  schema-v2 convention, automatic bounded-volume selection drives real CPU TSDF fusion, and the
  30-frame slice reports metric accuracy/completeness/F-score/normal error against its reference
  mesh. The extractor gate is closed independently; the stricter real-capture accuracy gate above
  remains open.
- [ ] [E2] **R2 production capture:** the iPad LiDAR companion now has permission UX, a zero-copy
  RealityKit preview, normal-tracking/depth admission, a three-frame bounded writer queue, native
- YUV/depth strides, callback-time host timestamps, linear append-only recording, hash-verified
  interrupted-session recovery, motion/quality/backpressure-aware adaptive admission, counters,
  and file export. Device/format controls, richer diagnostics, real interruption evidence, and the
  30-minute soak remain open.
- [x] [E2] **Offline video input contract:** deterministic ImageIO keyframe admission rejects blur,
  exposure failures, low contrast, near duplicates, and appearance discontinuities; video uses
  sequential/local-window COLMAP matching; explicit camera-group manifests preserve device/lens/
  focal/calibration identity; and every sparse model is exported, validated, ranked, and recorded.
  Real Sony/iPad footage, geometric parallax selection, targeted cross-group matching, and E3
  reconstruction evidence remain open.
- [ ] [E0] **R3 visual odometry:** calibrated initialization, PnP/local mapping, confidence, tracking
  loss, relocalization, submaps, and recorded trajectory metrics.
- [ ] [E2] **R4 depth providers:** MavebCapture records Apple scene depth/confidence/intrinsics/poses;
  schema-v2 desktop replay verifies hashes, converts coordinates and confidence, and fixture-tests
  TSDF-compatible packets. Real-device E3 evidence, the licensed RGB-depth bakeoff, uncertainty,
  temporal filtering, and RGB scale alignment remain open.
- [x] [E3] **RGB textured-mesh baseline:** native Apple photogrammetry produces checkpointed,
  provenance-hashed textured USDZ from deterministic video frames and Blender converts it to a
  validated material-bearing GLB. Custom RGB depth and LiDAR/Sony fusion remain R4 work.
- [x] [E2] **Sony+iPad metric alignment foundation:** robust deterministic camera-pose Sim(3),
  outlier rejection, degeneracy checks, metric position/orientation quality gates, verified capture
  replay, and complete metric COLMAP camera-rig export pass synthetic artifact tests. A paired
  physical capture and measured E3 report remain open.
- [x] [E2] **R5 sparse CPU reference:** deterministic power-of-two voxel blocks preserve the dense
  oracle's projection/fusion equations and resolved extraction exactly on a translated/rotated
  fixture; a billion-voxel logical room allocates only local observed blocks, and resident,
  candidate, extraction, disjoint-ray, and footprint-overflow failures are bounded and
  transactional. Extraction still uses a bounded dense active-span snapshot.
- [x] [E2] **Canonical Asset v1 contract:** `.aether` can represent a self-contained metric textured
  GLB, calibrated camera rig, explicit per-vertex confidence, coordinate convention, and hashed
  geometry/appearance provenance without pretending the proxy mesh is canonical geometry or
  requiring Gaussian content. Real Sony+iPad fusion into this frame remains an E3 gate.
- [x] [E2] **Native static GLB authoring:** deterministic bounded export preserves indexed geometry,
  vertex colors, static instances, embedded PNG/JPEG images, core PBR materials, samplers, and UV
  transforms. Animation, skins, morph targets, malformed topology, and hostile limits fail rather
  than being silently dropped. USDZ ingestion remains the explicit Blender-backed Apple baseline.
- [ ] [E0] **R5 real-time fusion:** sparse Metal volume, dirty-block meshing, snapshot isolation,
  memory pressure, persistence, and CPU/GPU agreement.
- [ ] [E0] **R6 Studio workflow:** immutable stage snapshots, explicit modes, recovery controls, and
  truthful per-stage diagnostics.
- [ ] [E0] **R7 hybrid completion:** reconstruction provenance/confidence, proxy shadow transfer,
  collision, navigation, particles, reflection probes, and multiple dynamic attachments.

Material relighting, cinematic expansion, and LOD expansion remain frozen until the reconstruction
and hybrid geometry critical path reaches E3.

## Phase 0 — Repository and build foundation

- [x] [E1] Preserve the original dirty working tree on an archive branch.
- [x] [E1] Move the maintained triangle into `examples/00_triangle`.
- [x] [E1] Remove tracked generated output, IDE state, duplicated samples, and sample archives.
- [x] [E1] Add CMake presets, strict warnings, sanitizer support, tests, and CPU CI configuration.
- [x] [E1] Remove source-controlled absolute machine paths.
- [x] [E1] Establish licensing, contribution, security, dependency, and architecture records.
- [x] [E1] Confirm a clean clone on a second filesystem path before merging.

## Phase 1 — Production Metal and application foundation

- [x] [E1] C++23 error, logging, profiling, and resource-location primitives.
- [x] [E1] Render-graph dependencies, dead-pass culling, resource lifetimes, and DOT export.
- [x] [E1] RAII Metal ownership and three bounded frames in flight.
- [x] [E1] Missing drawable/render-pass/encoder safety and GPU debug labels.
- [x] [E1] Offline `.metal` → `.air` → `.metallib` build embedded in the application bundle.
- [x] [E1] SwiftUI shell and opaque Objective-C++ viewport bridge.
- [x] [E1] Upload/readback rings, deferred destruction, transient heaps, pipeline binary archive, and GPU
  timestamps.
- [x] [E1] Job system, diagnostics bundle, app document model, autosave, undo/redo, and preferences.
- [x] [E1] Thirty-minute uninterrupted render soak with post-run heap inspection.
- [x] [E1] API-validation GPU frame capture confirming named passes and resources.

## Phase 2 — Mesh/PBR renderer

- [x] [E1] Generation-safe scene transforms, reverse-Z cameras, and keyboard/mouse fly controls.
- [x] [E1] Versioned camera-path JSON, atomic persistence, validation, and interpolated playback sampling.
- [x] [E1] Bounded glTF 2.0 parsing, indexed meshes, generated normals, and material factors.
- [x] [E1] Bounded glTF image ingestion, ImageIO decode, mipmaps, samplers, generated/imported tangents,
  core PBR texture maps, normal mapping, alpha masking, and alpha blend pipeline.
- [x] [E1] Default-scene traversal, nested node transforms, shared mesh instances, inverse-transpose
  normal transforms, bounded instance counts, and stable back-to-front transparent draw sorting.
- [x] [E1] Per-texture-slot `KHR_texture_transform` scale, rotation, and offset through CPU/MSL ABI.
- [x] [E1] Bounded glTF TRS animation loading, STEP/LINEAR/CUBICSPLINE evaluation, quaternion slerp,
  loop/clamp controls, hierarchical world resolution, and live mesh-instance playback.
- [x] [E1] Bounded glTF skins, JOINTS_0/WEIGHTS_0 normalization, inverse-bind validation, animated joint
  palettes, mirrored transforms, and Metal position/normal/tangent skinning.
- [x] [E1] Bounded glTF POSITION/NORMAL/TANGENT morph targets, mesh defaults, node overrides, GPU
  target-major delta buffers, and morph-before-skin vertex evaluation.
- [x] [E1] Reverse-Z depth, directional GGX PBR, exposure, and ACES-style tone mapping.
- [x] [E1] Resize-safe RGBA16F scene color and Depth32F reverse-Z targets, linear PBR/Gaussian
  composition, dedicated ACES presentation pass, EV exposure control, and fully bound fallback
  material resources validated through Metal's API layer.
- [x] [E1] Validated directional/point/spot light model, deterministic 16x9x24 logarithmic clusters,
  conservative screen/depth bounds, hard reference budgets, per-frame GPU lists, inverse-square
  range windows, spot cones, and multi-light GGX accumulation.
- [x] [E1] Bounded deterministic HDR equirectangular sampling, cosine irradiance convolution, GGX
  prefilter mips, split-sum BRDF LUT, cube/LUT Metal uploads, neutral fallbacks, and PBR IBL.
- [x] [E1] Practical directional cascade splits, bounded world-frustum slicing, stable texel-snapped
  orthographic light matrices, Metal depth convention, and degeneracy validation.
- [x] [E1] Four-slice directional shadow rendering with shared morph/skin bindings, alpha-mask cutouts,
  per-frame palette reuse, live cascade receivers, bias controls, and 3x3 comparison PCF.
- [x] [E1] Bounded spot/point shadow projection, fixed-budget allocation, deformation-aware caster
  submission, exact source-light matching, dominant-axis point faces, and 3x3 PCF receiving.
- [x] [E1] Directional cascade transition blending over the final ten percent of each split interval.
- [x] [E1] Camera-reprojected TAA with Halton jitter, depth rejection, neighborhood clipping, history
  invalidation, and two-stage soft-knee HDR bloom.
- [x] [E1] Two-frame offscreen MTK submission covering local shadows, temporal history, bloom, and
  presentation under Metal API and shader validation.
- [x] [E1] Asynchronous one-shot BGRA8 frame capture and bounded second-frame golden metrics for the
  complete HDR presentation path.
- [x] [E1] SHA-256-keyed Metal binary archives, preventing stale shader/ABI cache deserialization after
  application upgrades.
- [x] [E1] Depth-tested R32Uint mesh entity picking through C++, Objective-C++, and SwiftUI, with visible
  entity and background integration assertions.
- [x] [E1] Immutable engine-owned mesh entity-name snapshots and a SwiftUI outliner keyed to renderer
  selection IDs.
- [x] [E1] Validated mesh world-TRS overrides, numeric SwiftUI transform inspector, schema-v2 project
  persistence, reset behavior, and schema-v1 migration.
- [x] [E1] Engine-owned material snapshots, bounded factor overrides/reset, SwiftUI material inspector,
  and project-persisted material overrides.
- [x] [E1] Bounded directional/point/spot light mutation API and project-persisted SwiftUI light editor
  with add/remove and type-specific controls.
- [x] [E1] Depth-tested Metal RGB translation gizmo with reserved axis IDs, zoom-aware drag scaling,
  validated transform mutation, bridge callbacks, and project persistence.
- [x] [E1] RGBA16 rigid motion-vector/previous-depth target consumed by TAA, with translated-entity GPU
  readback validation.
- [x] [E1] Previous-pose joint palettes and morph weights evaluated in morph-before-skin order for
  deforming motion vectors.
- [x] [E1] Selectable directional-cascade and local-light shadow-map diagnostics in Studio.
- [x] [E1] Gaussian reverse-Z scene depth and camera-motion reprojection for temporal history.
- [x] [E1] Isolated PBR, directional/local shadow, and Gaussian capture goldens with bounded metrics,
  portable review artifacts, and exact per-run SHA-256 provenance.
- [x] [E1] Rotation and scale gizmo modes with validated persistent TRS updates.
- [x] [E1] Schema-v3 generalized Studio serialization for viewport, selection, camera, playback,
  transforms, materials, and lights with v1/v2 migration.

## Phase 3 — Standard Gaussian renderer

- [x] [E1] Strict bounded ASCII/binary-little-endian PLY/3DGS import and canonical binary codec.
- [x] [E1] Deterministic CPU anisotropic projection and front-to-back compositing oracle.
- [x] [E1] Bounded Metal 3 projection, covariance, culling, scan, stable radix ordering, tile ranges,
  compositing, depth/IDs, counters, and app presentation correctness path.
- [x] [E1] Pixel-level CPU/GPU agreement test and explicit tile-entry overflow test.
- [x] [E1] Hierarchical 256-threadgroup overlap scan with cross-block CPU/GPU validation.
- [x] [E1] Indirect-dispatch stable parallel radix with cross-block CPU/GPU compositing validation and
  executable serial compatibility fallback.
- [ ] [E2] M1/M2 named-scene performance exit gates.
- [x] [E1] Benchmark schema-v2 peak counter aggregation, synchronized CPU-frame timing, and executable
  GPU-p95/memory budget failure gates.
- [x] [E1] Degree 0–3 GraphDECO-order spherical-harmonic appearance in CPU and Metal paths.
- [x] [E1] Real GPU ID-target Gaussian picking bridged into SwiftUI source-ID selection.
- [x] [E1] SwiftUI-selectable depth, source-ID, tile-occupancy, and accumulated-opacity GPU views.
- [x] [E1] GPU visualizations for dominant-contributor SH degree and normalized per-tile sort rank.
- [ ] [E0] Research/debug visualizations for ellipsoid geometry and future hierarchy clusters.

## Phase 4 — Fully local reconstruction

- [x] [E1] Version-pinned COLMAP 3.13.0 and Brush 0.3.0 process adapters with direct argv execution,
  version checks, deterministic seeds, cancellation forwarding, logs, hashed provenance, atomic
  stage markers, and tested resume behavior.
- [x] [E1] ImageIO-backed capture validation with real decode rejection, bounded thumbnail analysis,
  image dimensions, EXIF camera/exposure fields, luminance consistency, relative sharpness,
  source sizing, deterministic ordering, structured issues, and machine-readable output.
- [x] [E1] Studio Reconstruction workspace with native validation reports, explicit dependency selection,
  bundled process helper, atomic-marker progress, cancellation, and resume-safe job output.
- [x] [E1] Strict COLMAP text-model validation for registered-image ratio, multi-view tracks, overlap-graph
  connectivity, camera baseline, and angular diversity, with an atomic JSON report and hard Brush gate.
- [x] [E1] Pinned Open3D 0.19 proxy tool with bounded COLMAP parsing, deterministic Poisson reconstruction,
  cleanup/decimation budgets, atomic hashed provenance, locked environment, and isolated tests.
- [x] [E2] Synthetic end-to-end reconstruction smoke test
- [ ] [E0] Real calibrated object capture
- [ ] [E0] Real indoor capture
- [ ] [E0] Real outdoor capture
- [ ] [E0] Published inputs, parameters, artifacts and quality metrics
- [x] [E1] Strict Brush milestone validation, torn-checkpoint fallback, geometry-state resume, stable final
  export, and explicit optimizer-state limitation in provenance.
- [x] [E1] Numerically ordered Brush milestone discovery and side-by-side Metal comparison viewports with
  synchronized cameras in Studio.

## Phase 5 — Hybrid worlds

- [x] [E1] Strict Open3D ASCII/binary triangle-PLY import, canonical proxy-mesh chunk v1, pack-time
  conversion, hostile-input checks, and real generated-proxy package verification.
- [x] [E1] Canonical proxy upload and dedicated reverse-Z depth, world-normal/confidence, surface-ID,
  and motion G-buffer with named Metal passes and GPU-validated readback.
- [x] [E1] Confidence-aware proxy/Gaussian depth composition with an occlusion golden that proves a
  foreground proxy suppresses a behind-surface Gaussian while preserving proxy motion/depth.
- [x] [E1] One transactional, replaceable glTF attachment per captured scene with persistent Studio
  document state, independent mesh/Gaussian ID namespaces, editable entities/materials, and
  front/behind proxy depth goldens.
- [ ] [E0] Multiple dynamic asset attachments, proxy shadow receiving and transfer, collision queries,
  particles, reflection probes, and navigation surfaces.

## Phase 6 — Material-aware relighting

- [ ] [E0] Frozen pending reconstruction/hybrid E3: material Gaussian schema, staged optimizer,
  constrained residuals, held-out evaluation, and
  five explicit ablation modes.

## Phase 7 — LOD, compression, and streaming

- [x] [E1] Versioned, random-access `.aether` container with per-chunk compression and hashes.
- [ ] [E0] Clustered multiresolution representation, quantization, asynchronous streaming, budgets, and
  Metal 4 optional path.

## Phase 8 — Product and cinematic workflows

- [ ] [E0] Complete Studio workspaces, recovery, background tasks, timeline, cinematic effects, media
  output, migrations, signed updates, and tutorials.

## Phase 9 — Evaluation and release

- [x] [E1] Headless `.aether` + camera-path Metal benchmark with warmup, median/p95 GPU time, allocation,
  visibility, tile-entry, overflow, and early-termination JSON counters.
- [ ] [E0] Public and original datasets, full metrics/ablations, raw results, report, SBOM, notarized DMG,
  signed update feed, checksums, and reproducibility package.

## User-owned gates

- Developer ID and notarization credentials stay in the user's Keychain/CI secret store.
- Final project name/trademark and public repository rename require user approval.
- Indoor/outdoor captures, location releases, asset licenses, manual proxy approval, cross-device
  hardware access, and any human-study consent require human action.
