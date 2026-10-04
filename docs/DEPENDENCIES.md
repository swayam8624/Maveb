# Dependency Policy

## Present

| Dependency | Purpose | License | Integration |
|---|---|---|---|
| Apple metal-cpp | C++ Metal bindings | Apache-2.0 | Vendored headers with license |
| Apple platform frameworks | Metal, MetalKit, AppKit, SwiftUI | Apple SDK terms | System frameworks |
| fastgltf 0.9.0 | Bounded glTF 2.0 parsing | MIT | FetchContent archive pinned by SHA-256 plus reviewed node-weight parser patch |
| simdjson 3.12.3 | Versioned camera-path JSON | Apache-2.0 | System config or pinned FetchContent archive |
| Zstandard 1.5.7 | Per-chunk `.aether` compression | BSD-3-Clause | Static FetchContent archive pinned by SHA-256 |
| COLMAP 3.13.0 | Local camera poses and sparse/dense reconstruction | BSD-3-Clause | External process pinned by commit |
| PoissonRecon Marching Cubes table | CPU isosurface correctness reference | BSD-3-Clause | Adapted table from the COLMAP-pinned source; no runtime linkage |
| Brush 0.3.0 | Local standard Gaussian training | Apache-2.0 | Cargo source build pinned by commit and lockfile |
| Open3D 0.19.0 | Deterministic sparse-point proxy reconstruction | MIT | Isolated Python 3.12 environment locked by `uv.lock` |

KairoMath was evaluated for scene math but is not consumed because its current repository has no
explicit license file. AETHER uses Apple SIMD until that legal boundary changes.

## Approved for later phases

| Dependency | Purpose | License boundary |
|---|---|---|
| Brush | Local standard 3DGS training baseline | Apache-2.0, separate pinned process |
| COLMAP | Camera calibration and structure from motion | BSD, separate pinned process |
| Open3D | Proxy cleanup, Poisson reconstruction, and decimation | MIT, isolated pinned process |
| Open3D | Automated proxy generation | MIT, separate tool/library after audit |
| Zstandard | `.aether` chunk compression | BSD, pinned library |
| Sparkle 2 | Signed application updates | MIT, app-only dependency |

Every dependency addition must record an immutable version/commit, source URL, checksum, license,
notices, update procedure, and whether its output may be redistributed. Dataset/model weights are
audited independently from their code.

The pinned fastgltf 0.9.0 release and upstream `main` at the time of integration invert the success
branch while parsing `node.weights`. AETHER applies
`cmake/patches/fastgltf-v0.9.0-node-weights.patch` during population. A clean out-of-tree build
verifies the patch before the morph-target fixture runs; remove it only after advancing to an
upstream revision with equivalent behavior.
