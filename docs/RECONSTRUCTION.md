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

`aether-reconstruct` runs seven external resumable stages: feature extraction, exhaustive matching,
seeded sparse mapping, text-model export, proxy generation, undistortion, and Brush training. After
export, an AETHER-owned gate parses the COLMAP text model and requires enough registered
images, multi-view tracks, overlap-graph connectivity, camera baseline, and angular diversity.
It writes `pose-coverage.json` atomically; a failed gate records `coverage-failed` in `job.json` and
does not launch proxy generation or Brush. A passing model feeds the pinned `aether-proxy` process;
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
does not serialize optimizer moments, so the schema-v3 manifest explicitly records
`optimizerStateRestored: false`; this is geometry-state recovery, not bit-exact optimizer recovery.
Before trusting any marker or checkpoint, AETHER compares `resume-key.txt` against a fingerprint of
the sorted input paths/sizes/hashes, seed, training/checkpoint budgets, and proxy configuration.
Changed inputs or settings require a new job directory; legacy jobs without a fingerprint are not
silently adopted.

Studio discovers only non-empty, canonically named `checkpoint_<iteration>.ply` milestones and
orders them numerically. The Reconstruction workspace can render any two milestones side-by-side in
independent Metal viewports driven by one shared camera, so geometry/appearance progress is compared
from the same view rather than from unrelated screenshots.

COLMAP 3.13.0 is selected because it provides a deterministic `random_seed` option. AETHER's job
manifest preserves the seed, full argument vectors, pinned identities, sorted input sizes/SHA-256
hashes, expected outputs, sparse-coverage evidence, stage logs, and resume markers. It verifies all
external-tool versions before starting. `--dry-run --json` validates inputs and emits every external
command without launching a tool.

## Recorded metric RGB-D oracle

`aether-fuse --auto-bounds` performs a deterministic prepass over calibrated metric depth. It
samples depth in world space, applies confidence rejection, trims declared extreme quantiles,
adds a fixed metric margin, and increases voxel size only when required by the configured maximum
dense-grid axis. The selected origin, dimensions, voxel size, truncation distance, and sample count
are emitted in JSON. A second replay performs weighted TSDF integration and atomically writes the
colored PLY; parent output directories are created by the CLI.

The dense volume remains a correctness oracle. Its automatic voxel growth makes larger captures
safe and bounded, but does not replace the future sparse Metal volume needed to preserve fine
resolution across a room.

`SparseTsdfVolume` is the deterministic CPU bridge between that oracle and the future Metal
backend. It preserves the dense implementation's nearest-pixel projection, confidence rejection,
normalized signed distance, weight saturation, color integration, and extraction topology while
allocating ordered 8-cubed voxel blocks only along valid depth-ray free space and the truncation
band. Candidate, resident, and extraction budgets fail transactionally: a rejected frame cannot
partially update an existing volume. Dirty block coordinates are stable and explicitly
acknowledged, which gives the Metal backend and incremental extractor a testable scheduling
contract. See [the sparse TSDF contract](formats/SPARSE_TSDF.md).

This CPU implementation is E2 fixture evidence, not the R5 production backend. It currently forms
a bounded dense snapshot of the allocated block span and invokes the resolved dense extractor.
Incremental block-border meshing, snapshot isolation, persistence/eviction, Metal allocation, and
real-capture CPU/GPU agreement remain open and the roadmap continues to label R5 incomplete.

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
