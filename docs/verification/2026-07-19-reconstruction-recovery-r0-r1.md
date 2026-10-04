# Reconstruction recovery R0/R1 verification

- Date: 2026-07-19
- Hardware: Apple M2 Pro
- Evidence: E2 synthetic/recorded fixtures; no E3 real-scene claim

## Implemented evidence

- Placeholder invented-motion tracker, luminance volume, prebuilt sphere, disconnected-quad
  extraction, silent camera fallback, live bridge, and Studio live controls are absent from
  production targets.
- Recorded capture schema v1 validates ordered frames, bounded calibrated dimensions, exact RGB and
  float-depth byte counts, relative paths, known poses, deterministic stepping, and injected
  failures.
- The CPU reference integrates `observedDepth - voxelCameraDepth`, confidence, pose confidence,
  truncation, weights, observations, and color.
- Unobserved volumes reject extraction.
- The plane fixture extracts shared cube-edge vertices and valid, non-degenerate triangles.
- Identical mesh inputs produce identical atomic binary PLY output.
- `aether-fuse` validates and executes the recorded capture → known pose/depth → TSDF → PLY path.

## Commands and results

```text
cmake --preset ci
cmake --build --preset ci --parallel
ctest --preset ci
Result: 9/9 passed

cmake --preset debug
cmake --build --preset debug --parallel
ctest --preset debug
Result: 15/15 passed

cmake --preset sanitizer
cmake --build --preset sanitizer --parallel
ctest --test-dir build/sanitizer --output-on-failure
Result: 9/9 passed

MTL_DEBUG_LAYER=1 MTL_SHADER_VALIDATION=1 ./build/debug/tests/AetherMetalTests
Result: passed with Metal API and GPU validation enabled
```

## Open gates

- Classic Marching Cubes case-table parity and ambiguous-case fixtures.
- Synthetic sphere Chamfer target.
- Real calibrated RGB-D capture and median/p95 geometry errors.
- Normal error and surface-sampled, rather than vertex-only, evaluation.
- Sparse volume, asynchronous scheduling, tracking, RGB depth, LiDAR, and live UI.
