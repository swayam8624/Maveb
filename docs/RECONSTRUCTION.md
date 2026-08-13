# Local reconstruction dependencies

AETHER keeps COLMAP and Brush out of the application process. Versions are frozen in
`dependencies/reconstruction.lock.json`; adapters exchange files through a versioned job directory
and record commands and provenance. No CUDA or cloud service is part of the macOS path.

Run `tools/bootstrap-reconstruction.zsh` to clone the exact Brush 0.3.0 commit and build its
`brush_app` CLI with Cargo's committed lockfile. The script never invokes `sudo`, Homebrew, or a
package-manager install. It checks for COLMAP 3.13.0; if absent, it prepares the pinned source and
stops with a clear handoff because COLMAP's native dependencies are a machine-level choice.

The expected private tool directory is `.aether-deps/bin`, ignored by Git. Source commits are
verified after checkout. Public releases must additionally archive dependency notices, the lock
manifest, build logs, and checksums of redistributed binaries.

The same bootstrap creates an isolated Python 3.12 environment for `aether-proxy` using the
committed `tools/aether-proxy/uv.lock`. Open3D 0.19.0 and every transitive wheel are version- and
hash-locked; nothing is installed into the user's system Python.

`tools/run-mavebbench.zsh` selects that pinned Python first and honors an explicit
`MAVEB_PYTHON` override. Benchmark geometry never accidentally depends on a global NumPy/Open3D
installation.

`aether-reconstruct` runs resumable feature extraction, configured matching, seeded sparse mapping,
per-model text export, model selection, proxy generation, undistortion, and Brush training. It never
assumes that COLMAP model `0` is usable. Every numeric sparse model is exported and parsed
independently. The AETHER-owned gate requires enough registered images, multi-view tracks,
overlap-graph connectivity, camera baseline, and angular diversity; structurally broken models
remain visible as rejected candidates instead of hiding a valid sibling model. Registered image
names must also belong to the exact selected input list, preventing a stale model with plausible
counts from being resumed against different frames.

`sparse-selection.json` records every candidate and the deterministic ranking reason. The winning
model is copied to `sparse/selected-text` and its metrics are written to `pose-coverage.json`. If no
model passes, `job.json` records `coverage-failed` and proxy generation and Brush never launch. The
selected model feeds the pinned `aether-proxy` process;
its mesh and report land under `<job>/proxy`. Every subprocess receives an argument vector directly—never a shell
command—while stdout/stderr go to separate stage logs. Completion markers are written atomically
only after the process exits successfully and its expected output exists. SIGINT and SIGTERM are
forwarded to the active child.

Studio treats pose validation as an explicit progress stage and renders the persisted registration,
track, overlap, baseline, view-angle, and issue evidence for both completed and rejected jobs.

The adapter runs Brush in CLI mode using the pinned v0.3.0 interface:

```bash
brush <COLMAP-dataset> --seed 42 \
  --total-steps 30000 --export-every 5000 \
  --export-path <job>/exports --export-name 'checkpoint_{iter}.ply'
```

Completed milestones remain in `exports/`. On resume, AETHER scans newest-first, strictly parses each
candidate through its bounded 3DGS PLY importer, skips torn/corrupt newer files, atomically restores
the latest valid snapshot as `dense/init.ply`, and passes Brush the matching `--start-iter`. The final
validated milestone is atomically copied to the stable `base-gaussians.ply` interface. Brush 0.3.0
does not serialize optimizer moments, so the schema-v4 manifest explicitly records
`optimizerStateRestored: false`; this is geometry-state recovery, not bit-exact optimizer recovery.
Before trusting any marker or checkpoint, AETHER compares `resume-key.txt` against a fingerprint of
the ordered selected input paths/sizes/hashes, input kind, matcher and overlap, camera grouping,
image-list contents, preprocessing manifest, seed, training/checkpoint budgets, and proxy
configuration.
Changed inputs or settings require a new job directory; legacy jobs without a fingerprint are not
silently adopted.

Studio discovers only non-empty, canonically named `checkpoint_<iteration>.ply` milestones and
orders them numerically. The Reconstruction workspace can render any two milestones side-by-side in
independent Metal viewports driven by one shared camera, so geometry/appearance progress is compared
from the same view rather than from unrelated screenshots.

COLMAP 3.13.0 is selected because it provides a deterministic `random_seed` option. AETHER's
schema-v4 job manifest preserves the seed, input/matcher/camera contracts, full argument vectors,
pinned identities, ordered input sizes/SHA-256 hashes, expected outputs, sparse-selection and
coverage evidence, stage logs, and resume markers. It verifies all
external-tool versions before starting. `--dry-run --json` validates inputs and emits every external
command without launching a tool.

## Video keyframes and camera identity

Video is decoded to deterministic candidate frames first. `aether-keyframes` then uses bounded
ImageIO thumbnails to reject relative blur, extreme exposure, low contrast, near duplicates, and
appearance discontinuities. Its 16×16 normalized-correlation fingerprint is an appearance-overlap
proxy; it is not presented as metric parallax or optical flow. The tool atomically publishes:

```text
keyframes/
  selected-images.txt
  keyframes.json
```

The JSON report retains every frame decision and measurement. The list contains ordered paths
relative to the image root and is passed directly to COLMAP. A typical local run is:

```bash
aether-keyframes frames --output keyframes --json
aether-reconstruct frames --output reconstruction \
  --input-kind video \
  --image-list keyframes/selected-images.txt \
  --preprocessing-manifest keyframes/keyframes.json \
  --json
```

`--input-kind video` selects COLMAP's sequential matcher with a local overlap of ten by default.
Unordered photographs continue to use exhaustive matching. Both can be overridden explicitly, and
the resolved choice is part of the resume identity.

Single-camera video and still sets share one COLMAP camera by default. Multi-camera datasets must
place each camera group in its own direct child directory and provide a versioned camera-group
manifest; Maveb then uses `single_camera_per_folder`. Device, lens, focal length, and calibration
identity are recorded in `job.json`. See [the camera-group contract](formats/CAMERA_GROUPS.md).
This prevents silent intrinsic merging; targeted Sony+iPad cross-group matching and metric Sim(3)
alignment remain later gates and are not claimed by this adapter.

## Recorded metric RGB-D oracle

`aether-fuse --auto-bounds` performs a deterministic prepass over calibrated metric depth. It
samples depth in world space, applies confidence rejection, trims declared extreme quantiles,
adds a fixed metric margin, and increases voxel size only when required by the configured maximum
dense-grid axis. The selected origin, dimensions, voxel size, truncation distance, and sample count
are emitted in JSON. A second replay performs weighted TSDF integration and atomically writes either
colored PLY or deterministic static GLB; parent output directories are created by the CLI. The
[native GLB profile](formats/NATIVE_GLB_EXPORT.md) preserves vertex colors and can be reloaded by the
engine without an external converter.

The dense volume remains a correctness oracle. Its automatic voxel growth makes larger captures
safe and bounded, but does not replace the future sparse Metal volume needed to preserve fine
resolution across a room.

`SparseTsdfVolume` is the deterministic CPU bridge between that oracle and the Metal backend. It
preserves the dense implementation's nearest-pixel projection, confidence rejection,
normalized signed distance, weight saturation, color integration, and extraction topology while
allocating ordered 8-cubed voxel blocks only along valid depth-ray free space and the truncation
band. Candidate, resident, and extraction budgets fail transactionally: a rejected frame cannot
partially update an existing volume. Dirty block coordinates are stable and explicitly
acknowledged. Candidate selection is now a shared contract used by both backends. See
[the sparse TSDF contract](formats/SPARSE_TSDF.md).

`SparseMetalTsdfVolume` provides the first E2 Metal 3 fusion slice. The host assigns candidate and
resident block slots deterministically; Metal kernels classify candidate voxels and perform the
same calibrated depth, confidence, signed-distance, color, weight-saturation, and observation-count
updates as the CPU reference. Updates are fused into bounded private scratch storage and copied to
resident storage only after successful completion. Extraction consumers receive immutable CPU
snapshots tagged with a completed generation rather than live Metal resources.

`IncrementalSparseTsdfMesher` consumes that shared CPU/Metal snapshot schema and replaces only
patches affected by dirty samples. A patch owns cells by their minimum grid corner, reads a positive
topology halo and symmetric gradient halo, and invalidates negative neighbours when their cells can
reference a changed block. This yields exact full-extraction triangle coverage and bit-exact shared
positions/normals while allowing explicit patch removal and stale-generation rejection.

This remains fixture evidence, not the R5 production backend. CPU extraction still forms a bounded
dense active-span snapshot for full exports, and incremental patches still execute on the CPU.
Metal fusion is synchronous and is not wired to live reconstruction. GPU-resident meshing,
selective readback, asynchronous scheduling, persistence/eviction, real-capture CPU/GPU agreement,
and throughput/soak evidence remain open.

Isosurface correctness is verified independently from camera projection and fusion. A complete
normalized scalar field can instantiate the dense oracle directly, and a separately implemented
classic Marching Cubes case-table extractor provides the reference topology. The shipping dense
extractor retains its face-center asymptotic decision and shared-edge reuse because the exhaustive
and ambiguous-face fixtures prove closed manifold output while preserving deterministic topology.
`AetherOracleGeometryTests` regenerates the raw report for all 256 classic cases plus analytic
sphere, box, 30 mm thin-wall, disconnected-sphere, and torus fields.

## Local textured photogrammetry

`maveb-photogrammetry` uses Apple's `PhotogrammetrySession` as the production RGB mesh baseline.
It accepts a directory of stills or extracted video frames and produces a textured USDZ entirely
locally. Preview, reduced, medium, full, and raw details are explicit; sequential ordering is used
for video and unordered ordering for still photographs. Input hashes, configuration, rejected
samples, skipped samples, OS identity, and output path are written to an atomic provenance JSON.
Apple checkpoint directories remain outside Git and allow expensive stages to resume.

`tools/convert-usdz-to-glb.py` runs only inside Blender. It imports the preserved USDZ, requires at
least one mesh, exports a binary glTF with materials/textures, and returns machine-readable artifact
evidence. This establishes a serious textured-mesh baseline before AETHER attempts custom dense
RGB depth or cross-device LiDAR/Sony texture fusion.

## Sony and iPad metric alignment

`maveb-align-sensors` consumes a registered COLMAP text model, a fully verified exported
`.mavebcapture`, and explicit one-to-one visual camera matches. It robustly estimates the Sim(3)
that maps COLMAP's arbitrary-scale world into the iPad's metric world. Seeded RANSAC uses position
and orientation agreement, Huber refinement limits the influence of remaining position noise, and
the report records median/p95/maximum metric position and orientation errors plus every rejected
match. Degenerate or near-collinear camera motion cannot produce a successful transform.

The accepted output contains every registered COLMAP camera transformed into the metric capture
frame, not only the iPad cameras used for fitting. This is the contract that makes Sony cameras
metric before LiDAR fusion and multi-view texture projection. The camera axes must already share
Maveb's `+X right, +Y down, +Z forward` convention; COLMAP text poses and desktop-replayed
MavebCapture poses satisfy that contract.

Camera identity is currently explicit rather than guessed. The versioned match file maps the iPad
images admitted to the joint COLMAP reconstruction to their original capture frame IDs. Automatic
cross-device visual matching and joint bundle adjustment with ARKit priors are later refinements;
they are not silently claimed by this deterministic alignment gate. See
[the sensor-alignment format](formats/SENSOR_ALIGNMENT.md).
