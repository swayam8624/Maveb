# AETHER / Maveb

AETHER is a Metal-native captured-world research engine for Apple silicon. The project combines
metric reconstruction, Gaussian scene representations, conventional mesh/PBR rendering, package
provenance, and native macOS/iPad tooling.

> Current status: research / engineering prototype. The project does **not yet claim production
> Gaussian rendering or relighting**.

## What the system does

The intended pipeline is:

```text
real-world capture
    -> calibrated RGB / RGB-D evidence
    -> metric reconstruction
    -> canonical mesh + Gaussian assets
    -> versioned .aether package
    -> AetherStudio Metal viewport
```

The maintained reconstruction path works from recorded metric RGB-D/camera evidence. The old live
scanner path was intentionally removed rather than kept as an unvalidated demo.

## Responsive heavy-scene viewport

Large Gaussian captures can contain hundreds of thousands or millions of splats, while the standard
GPU path performs projection, tile counting, key generation/sorting, tile-range construction, and
compositing every frame. AetherStudio therefore treats navigation as a responsive preview workload
instead of a full-quality offline render.

The Studio preview path currently uses:

- adaptive drawable resolution while the camera/object is moving;
- motion-sensitive Gaussian budgets with progressive quality recovery after input settles;
- conservative early rejection of negligible low-opacity, sub-pixel, and safely off-screen splats;
- a deterministic 32x32x32 coarse spatial ordering for large captures so low-budget prefixes cover
  the whole scene instead of an arbitrary source-array prefix;
- canonical source-ID preservation through the reordered preview path;
- isolated background renderer construction for scene imports, followed by an atomic renderer swap,
  so heavy package decode/upload does not block the macOS UI or mutate the renderer being drawn.

This is a stepping stone toward a true hierarchical spatial Gaussian LOD/visibility structure. The
current path deliberately prioritizes editor responsiveness while keeping the full source asset
resident and unchanged.

## Main components

- `engine/core` - common errors, logging, diagnostics, timing and support utilities.
- `engine/gaussian` - canonical Gaussian assets, PLY loading/codecs and reference operations.
- `engine/mesh` - glTF/mesh loading and mesh utilities.
- `engine/scene` - camera, transforms, lighting, shadows and scene-domain logic.
- `engine/metal` - Apple Metal renderer, Gaussian GPU path and mesh/PBR rendering.
- `engine/package` - `.aether` package reading/writing, hashing and provenance.
- `engine/reconstruction` - metric reconstruction and reconstruction orchestration.
- `engine/capture` - capture package validation/processing.
- `apps/AetherStudio` - native macOS editor/research viewport.
- `apps/MavebCapture` - iPad metric RGB-D capture application.

## AetherStudio

AetherStudio is the native macOS front end for scene import, captured-world rendering, mesh/PBR
look-development, reconstruction workflows, research/debug views and benchmarking support.

Scene assets are imported inside a project. The project document extension is `.aetherproject`;
`.aether` is a captured-scene package rather than the document format itself.

Supported scene imports include:

- `.aether`
- Gaussian `.ply`
- `.gltf`
- `.glb`

## Build requirements

The primary target is Apple silicon macOS.

Typical requirements:

- macOS 15+
- Xcode 26+
- CMake 3.28+
- Ninja
- Xcode Metal Toolchain

Install the Metal compiler toolchain when needed:

```bash
xcodebuild -downloadComponent metalToolchain
```

Configure, build and test:

```bash
cmake --preset debug
cmake --build --preset debug
ctest --preset debug
```

Launch the Studio bundle:

```bash
open build/debug/apps/AetherStudio/AetherStudio.app
```

When LaunchServices rejects a locally built bundle because of host-version metadata, the executable
can also be launched directly for development diagnostics:

```bash
./build/debug/apps/AetherStudio/AetherStudio.app/Contents/MacOS/AetherStudio
```

## Gaussian renderer

The Metal Gaussian path includes projection, covariance construction, tile overlap generation,
prefix scans, depth/tile key generation, radix ordering, range building and front-to-back
compositing. Debug outputs include depth, source IDs, occupancy, opacity and other research views.

The responsive Studio shader is intentionally more conservative than the correctness/reference path:
it can reject contributions that are visually negligible during interaction before performing the
full covariance and spherical-harmonic work.

## Hybrid scene direction

AETHER is designed around captured static worlds plus conventional dynamic assets:

```text
captured Gaussian world
        +
dynamic glTF / PBR mesh
        ->
hybrid Metal viewport
```

This is intended to move captured environments closer to editable engine scenes rather than treating
them as static scan viewers.

## Reconstruction and packaging

The repository contains metric RGB-D/TSDF reconstruction tooling, deterministic mesh extraction,
coordinate-alignment tooling and `.aether` packaging utilities. Packages are versioned and carry
hashed/provenance-aware payloads rather than acting as an opaque model-file rename.

Common generated assets can include canonical textured GLB geometry, proxy geometry, Gaussian PLY
assets and packaged captured worlds.

## Validation

The codebase contains CPU/reference tests, Metal tests, reconstruction tests, package tests and
benchmark tooling. GPU/reference agreement and deterministic behavior are treated as first-class
engineering requirements rather than relying only on visual inspection.

## Repository policy

Performance preview mechanisms must not silently alter or overwrite canonical reconstruction data.
Viewport quality reduction is temporary/editor-side; the original Gaussian asset remains available
for correctness, export and future hierarchical LOD work.
