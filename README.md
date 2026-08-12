# AETHER

AETHER is a Metal-native research engine for reconstructing, rendering, relighting, and
interacting with captured Gaussian worlds on Apple silicon.

Reconstruction is currently in an oracle-first recovery: the former live camera panel was callback
plumbing, not a valid scanner, and has been removed from the shipping path. The maintained
reconstruction core now starts with versioned recorded metric RGB-D, known poses, calibrated TSDF
integration, deterministic isosurface extraction, atomic PLY output, and geometry metrics. Live
capture returns only after real-scene E3 evidence. See
[ADR 0005](docs/adr/0005-reconstruction-truth-and-oracle-first.md).

The repository is being rebuilt from the original `MetalPractice` learning project as a set of
verified, shippable milestones. The current foundation contains:

- A C++23 core with structured errors, profiling, logging, and safe resource discovery.
- A declarative render graph with dependency analysis, pass culling, resource lifetimes, and DOT
  export.
- A Metal renderer with RAII ownership, bounded frames in flight, capability reporting, drawable
  safety, and offline `.metallib` compilation.
- A SwiftUI macOS application whose Objective-C++ bridge keeps Metal objects out of Swift.
- A Swift 6 [MavebCapture iPad companion](apps/MavebCapture/README.md) that records checked,
  calibrated RGB + LiDAR packages for deterministic desktop fusion.
- A versioned, hashed, bounded, per-chunk compressed [`.aether` container](docs/formats/AETHER_PACKAGE.md)
  with `aether-pack` and `aether-inspect` command-line tools.
- A [Canonical Asset v1](docs/formats/CANONICAL_ASSET.md) profile that packages a self-contained
  metric textured GLB, calibrated cameras, per-vertex confidence, coordinate-frame semantics, and
  hashed geometry/appearance provenance without requiring Gaussian content.
- A bounded [standard 3DGS PLY importer](docs/formats/GAUSSIAN_PLY.md) and deterministic
  anisotropic CPU reference rasterizer.
- A Metal 3 Gaussian correctness path with projection, covariance, stable tile/depth ordering,
  bounded compositing, depth/IDs/counters, CPU/GPU agreement tests, and PLY/`.aether` presentation
  in AetherStudio, including click-to-pick source IDs and selectable depth, ID, occupancy, and
  opacity views from the real GPU attachments.
- A canonical proxy-mesh path with a dedicated reverse-Z normal/confidence/ID/motion G-buffer and
  confidence-aware Gaussian occlusion, verified by a real Metal golden and proxy-ID readback.
- A core glTF metallic-roughness path with bounded embedded/external image ingestion, ImageIO decode,
  generated mipmaps and tangents, glTF samplers, material texture maps, normal mapping, and alpha
  mask/blend states.
- A warnings-as-errors CPU CI path, sanitizer preset, and foundation tests.
- [MavebBench](benchmarks/README.md), a reproducible real-data evidence harness for ETH3D,
  Tanks & Temples, uCO3D, ARKitScenes, DTU and reference subsets. It records real tool commands,
  dataset/adaptor status, video preprocessing, camera-aligned geometry metrics and generated outputs
  without vendoring dataset bytes.

The project does **not** yet claim production Gaussian rendering or relighting. See
[the roadmap](docs/ROADMAP.md) for implemented and pending exit gates.

## Requirements

- Apple-silicon Mac running macOS 15 or newer.
- Xcode 26 or newer.
- CMake 3.28 or newer and Ninja.
- The separately downloadable Xcode Metal Toolchain.

Install the Metal compiler once if `xcrun metal` reports it is unavailable:

```bash
xcodebuild -downloadComponent metalToolchain
```

## Build and test

```bash
cmake --preset debug
cmake --build --preset debug
ctest --preset debug
open build/debug/apps/AetherStudio/AetherStudio.app
```

The iPad recorder is built separately with the Xcode generator:

```bash
cmake -S apps/MavebCapture -B build/ipad-capture -G Xcode \
  -DCMAKE_SYSTEM_NAME=iOS -DCMAKE_OSX_DEPLOYMENT_TARGET=17.0
cmake --build build/ipad-capture --config Debug -- \
  -sdk iphoneos CODE_SIGNING_ALLOWED=NO
```

CPU-only CI and sanitizer configurations do not require the app target:

```bash
cmake --preset ci
cmake --build --preset ci
ctest --preset ci

cmake --preset sanitizer
cmake --build --preset sanitizer
ctest --test-dir build/sanitizer --output-on-failure
```

Release configuration intentionally fails if the Metal Toolchain is missing.

## Reconstruction dependencies

The local RGB reconstruction adapter uses pinned COLMAP, Brush and `aether-proxy` versions under
`.aether-deps/`. On Apple Silicon, after the documented native COLMAP libraries are installed, the
full private tool setup can be bootstrapped with:

```bash
AETHER_BUILD_COLMAP=1 ./tools/bootstrap-reconstruction.zsh
```

The bootstrap never writes dependency binaries into the repository and does not silently accept a
mismatched COLMAP version.

## Package and benchmark

```bash
build/debug/tools/aether-pack/aether-pack scene-directory --output scene.aether --json
build/debug/tools/aether-inspect/aether-inspect scene.aether --json
build/debug/apps/AetherBenchmark/aether-benchmark scene.aether \
  --camera-path camera-path.json --width 1920 --height 1080 --json
build/debug/tools/aether-capture/aether-capture validate dataset/images --json
build/debug/tools/aether-reconstruct/aether-reconstruct dataset \
  --output reconstruction-job --trainer brush --seed 42 --dry-run --json
build/debug/tools/aether-fuse/aether-fuse recorded-capture \
  --output proxy.ply --voxel 0.01 --truncation 0.04 --json
```

For the real-data regression layer:

```bash
export MAVEB_DATA="$HOME/Datasets/MavebBench"
./tools/run-mavebbench.zsh doctor
./tools/run-mavebbench.zsh run eth3d-pipes --steps 2000 --checkpoint-every 1000
./tools/run-mavebbench.zsh run uco3d-object --video-fps 2 --steps 2000
./tools/run-mavebbench.zsh run arkitscenes-47333462 --arkit-max-frames 30
./tools/run-mavebbench.zsh report --output benchmarks/latest-report.md
```

The benchmark performs warmup frames, waits for each real Metal command buffer, and reports GPU
median/p95 time plus allocation and Gaussian workload counters. See
[the benchmark contract](docs/BENCHMARKING.md). Serial kernels are compatibility fallbacks only, and
tiny-fixture timings are never used as release performance claims.

## Repository history

The complete pre-migration working tree, including uncommitted tutorial work and generated build
state, is preserved on `archive/metal-practice-2026-07-12`. The maintained tutorial is under
`examples/00_triangle`; generated artifacts and IDE user state are excluded from the flagship
branch.

## License

AETHER source code is licensed under Apache-2.0. Documentation is licensed under CC BY 4.0 unless
its file says otherwise. Datasets and third-party assets have separate manifests and are never
implicitly covered by the code license.
