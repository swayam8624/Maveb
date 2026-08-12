# MavebBench

MavebBench is the repository's evidence layer for real reconstruction data. Dataset bytes stay
outside Git under `MAVEB_DATA`; committed manifests describe how to locate them. The harness does
not turn missing evidence into fake passes.

## Setup

```bash
export MAVEB_ROOT="$HOME/Desktop/Programming/Maveb"
export MAVEB_DATA="$HOME/Datasets/MavebBench"
export PATH="$MAVEB_ROOT/.aether-deps/bin:$PATH"

cmake --preset debug
cmake --build --preset debug
AETHER_BUILD_COLMAP=1 ./tools/bootstrap-reconstruction.zsh
```

The bootstrap keeps Brush, COLMAP, `aether-proxy`, Open3D and their pinned identities under
`.aether-deps/`.

## Commands

```bash
./tools/run-mavebbench.zsh doctor
./tools/run-mavebbench.zsh list

# RGB baseline: validation -> COLMAP -> coverage gate -> proxy -> Brush -> ETH3D GT metrics.
./tools/run-mavebbench.zsh run eth3d-pipes --steps 2000 --checkpoint-every 1000

# Video path: candidate decode -> validation -> keyframe admission -> sequential COLMAP.
./tools/run-mavebbench.zsh run uco3d-object --video-fps 12 --steps 2000

# Apple RGB-D/LiDAR: conversion -> automatic bounds -> real TSDF -> PLY -> metric report.
./tools/run-mavebbench.zsh run arkitscenes-47333462 \
  --arkit-max-frames 30 --arkit-max-axis 96 --arkit-voxel 0.02

# RGB video: deterministic frames -> local Apple textured USDZ -> Blender-ready GLB.
./tools/run-mavebbench.zsh run uco3d-object --skip-reconstruction \
  --photogrammetry --photogrammetry-detail medium --convert-glb

# Fast suite planning without launching COLMAP/Brush.
./tools/run-mavebbench.zsh suite smoke --dry-run

./tools/run-mavebbench.zsh report --output benchmarks/latest-report.md
```

Generated frames, converted captures, jobs, aligned point clouds, logs and reports live under
`benchmarks/results/` and are ignored by Git.

`--video-fps` controls deterministic candidate decoding, not the final reconstruction frame rate.
`aether-keyframes` records quality and appearance-overlap decisions in `keyframes.json`; only the
ordered `selected-images.txt` set reaches feature extraction and mapping. Video reconstruction uses
the sequential matcher rather than exhaustive all-pairs matching.

## Geometry evaluation

ETH3D manifests include the official evaluation laser point cloud and calibrated reference camera
poses. Maveb's monocular COLMAP reconstruction has an arbitrary similarity transform, so the
benchmark aligns the reconstructed camera centres to the calibrated ETH3D camera centres using an
Umeyama Sim(3) fit. It then applies that transform to the proxy mesh and computes bidirectional
nearest-neighbour accuracy/completeness, symmetric mean Chamfer, p95 distances, and F-scores at
1/2/5 cm using the same pinned Open3D environment as `aether-proxy`.

The alignment method and matrix are written into every evaluation result. These are proxy-geometry
metrics, not a claim that the current sparse-SfM Poisson proxy is final production geometry.

## ARKitScenes adapter

`benchmarks/scripts/adapters/arkitscenes_to_aether.py` converts the official low-resolution raw
sequence without mutating the dataset. It synchronizes RGB/depth/intrinsics/poses by timestamp,
converts uint16 millimetre depth to float32 metres, converts RGB PNGs to NV12 luma/chroma planes,
preserves ARKit confidence levels, hashes every plane, writes the exact schema-v2 coordinate
contract consumed by `RecordedSequenceSource`, derives robust bounded volume settings from metric
depth, and executes the deterministic CPU TSDF oracle. Partial-sequence evaluation crops the
reference to the reported candidate bounds plus a fixed margin; it never presents that local
completeness score as whole-room coverage.

The dense CPU TSDF remains a bounded correctness oracle. MavebBench therefore does not pretend a
full room-scale ARKitScenes fusion is a production real-time path; sparse Metal fusion remains a
separate roadmap gate.

## Textured photogrammetry

`maveb-photogrammetry` is a native Swift 6 command-line adapter around Apple's local
`PhotogrammetrySession`. It validates the input set, supports preview/reduced/medium/full/raw
quality, unordered stills or sequential video frames, checkpoint recovery, object masking,
structured JSON errors, atomic model replacement, and a provenance manifest with every input
SHA-256. The native artifact is a textured USDZ. `--convert-glb` invokes the installed Blender in
background mode through `tools/convert-usdz-to-glb.py`, verifies that a mesh was imported, and
produces a textured binary glTF without modifying the USDZ source.

## Status semantics

`pass` means the named command actually completed and produced parseable success evidence.
`fail` means an executable or dataset step ran and failed. `blocked` means a required executable or
reference is missing. `adapter-required` is a deliberate engineering gate currently retained for
DTU's benchmark-specific camera/reference conversion. `reference-only` means the dataset is present
but is not currently a reconstruction input.

## Initial evidence

The first real baseline on Apple Silicon used ETH3D Pipes with the pinned dependency set:

- 14 / 14 images registered.
- 3,154 tracked sparse points.
- Sparse coverage gate passed with full connectivity.
- Proxy generation produced 3,778 vertices and 7,242 triangles.
- Brush produced valid checkpoints and `base-gaussians.ply` at 2,000 smoke-test steps.

Those numbers are a smoke baseline, not a final quality claim. Regenerate geometry metrics locally
with the committed benchmark rather than copying numbers into future reports.

## Dataset policy

Dataset licenses are independent of the Apache-2.0 source license. MavebBench never vendors the
downloaded datasets. Keep commercial/publication usage consistent with each dataset's original
terms.
