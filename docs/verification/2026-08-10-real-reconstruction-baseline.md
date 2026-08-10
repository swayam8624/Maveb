# 2026-08-10 real reconstruction baseline

This record captures the first real-data end-to-end reconstruction evidence used to seed MavebBench.
It is a smoke/contract result, not a final quality or performance claim.

## Environment

- Baseline source revision: `75fdc4e7d95282de7abd6f980597b560a390cef4`.
- Apple-silicon macOS path with CUDA disabled.
- Pinned reconstruction tools: COLMAP 3.13.0, Brush 0.3.0, `aether-proxy` 0.1.0 / Open3D 0.19.0.
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

## Benchmark capabilities added from this baseline

MavebBench makes those results reproducible instead of leaving them as terminal transcripts:

- ETH3D Pipes/Meadow manifests now include evaluation scans and calibrated reference cameras.
- `evaluate_geometry.py` aligns reconstructed cameras to reference cameras with an explicit Sim(3)
  and reports bidirectional geometry errors plus F-scores at 1/2/5 cm.
- uCO3D/ordinary video gets deterministic ffmpeg frame ingestion before entering the maintained
  still-image reconstruction path; the report records the extraction command and frame count.
- ARKitScenes raw RGB-D is converted to the exact MavebCapture schema-v2 plane/pose/calibration
  contract and passed through `aether-fuse --dry-run` to validate the real native reader contract.
- Dataset bytes and generated results remain outside Git.

## Remaining gates

The benchmark does not erase the project's remaining research work:

- Uniform video sampling is a deterministic baseline, not the future adaptive blur/overlap/baseline
  keyframe selector.
- The current RGB editable proxy still comes from sparse COLMAP points followed by Poisson; dense
  production RGB geometry remains a major gap.
- The ARKitScenes adapter is contract-tested in code, but a local run on the downloaded sequence is
  still required before publishing ARKitScenes fusion/accuracy evidence. The current dense CPU TSDF
  is an oracle, not the room-scale real-time implementation.
- DTU retains a benchmark-specific camera/reference adapter gate.
- Blender-ready GLB export, surface-bound residual appearance, `.aether` v2 rate-distortion/LOD,
  sparse Metal fusion and the later Vulkan backend remain roadmap milestones.

MavebBench preserves these boundaries in machine-readable run records so future work can turn a
gate into PASS only when the implementation and evidence exist.
