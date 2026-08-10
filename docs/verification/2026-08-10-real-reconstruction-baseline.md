# 2026-08-10 real reconstruction baseline

This record captures the first real-data end-to-end reconstruction evidence used to seed MavebBench.
It is a smoke/contract result, not a final quality or performance claim.

## Environment

- Baseline source revision: `75fdc4e7d95282de7abd6f980597b560a390cef4`.
- Apple-silicon macOS path with CUDA disabled.
- Pinned reconstruction tools: COLMAP 3.13.0, Brush 0.3.0, and `aether-proxy` 0.1.0.
- The complete native test suite passed: 15/15 tests.

## ETH3D Pipes smoke reconstruction

Input was the 14 undistorted DSLR images from the ETH3D Pipes scene. The run used seed 42 and a
reduced Brush budget of 2,000 steps with checkpoints every 1,000 steps so it could prove the full
adapter contract without being presented as a converged visual-quality result.

Observed evidence:

- 14/14 input images registered.
- 3,154 tracked sparse points were accepted by the AETHER pose/coverage gate.
- Sparse coverage passed with a connected overlap graph.
- The sparse-to-proxy stage produced 3,778 vertices and 7,242 triangles.
- Brush emitted valid 1,000- and 2,000-step checkpoints.
- The final 2,000-step checkpoint passed AETHER's bounded 3DGS PLY validation and was promoted to
  `base-gaussians.ply`.

This proves the maintained still-image path can execute the intended external-tool sequence on real
photographs: validation -> COLMAP feature/matching/mapping -> AETHER sparse coverage gate -> proxy
mesh -> undistortion -> Brush -> validated Gaussian output.

## Remaining benchmark gates

The baseline also established the following explicit boundaries rather than hiding them:

- uCO3D source videos require video-to-image ingestion before the current image reconstruction
  adapter can run. MavebBench owns that deterministic preprocessing path and records its provenance.
- Raw ARKitScenes packages are not silently treated as MavebCapture schema-v2. They stay
  `adapter-required` until timestamp, calibration, depth/confidence, and coordinate transforms are
  mapped and validated against `aether-fuse`.
- DTU remains an evaluation adapter gate until its cameras/reference geometry are normalized into
  AETHER's metric evaluation contract.
- OmniObject3D is currently reference-only in the smoke suite.

MavebBench preserves these statuses in machine-readable run records so future work can turn a gate
into PASS only when the corresponding adapter and evidence exist.
