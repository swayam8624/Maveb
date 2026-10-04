# AETHER Public Evaluation & Benchmark Suite

This document defines the canonical public evaluation bundle, datasets, camera paths, and validation instructions to guarantee reproducible real-time rendering and reconstruction results.

---

## 1. Datasets & Scenes

To evaluate AETHER's hybrid rendering and reconstruction performance under diverse scene characteristics, we recommend three standard datasets:

1. **Mip-NeRF 360 (Bicycle / Garden)**: Complex, highly textured outdoor objects with rich background detail. High depth variation tests parallel radix sorting and spherical-harmonic (SH) representation.
2. **Deep Blending (Playroom)**: Fine-grained indoor geometry with specular reflections and complex occlusion.
3. **Tanks and Temples (Barn / Truck)**: Large-scale outdoor scenes that benchmark COLMAP sparse reconstruction, Open3D Poisson surface reconstruction, and hybrid depth composition.

---

## 2. Running an End-to-End Reconstruction

You can run a complete multi-view reconstruction using the `aether-reconstruct` pipeline.

```bash
# Execute end-to-end pipeline from raw images
./build/debug/tools/aether-reconstruct/aether-reconstruct \
    <image-directory> \
    --output ./reconstruction-job \
    --colmap .aether-deps/bin/colmap \
    --brush .aether-deps/bin/brush \
    --proxy .aether-deps/bin/aether-proxy \
    --steps 30000 \
    --seed 42
```

### Process Stages
1. **`feature-extraction`**: Extracts SIFT descriptors from inputs using COLMAP.
2. **`feature-matching`**: Runs geometric verification and matches features.
3. **`sparse-mapping`**: Performs incremental Structure-from-Motion (SfM) to reconstruct sparse cameras and a 3D point cloud.
4. **`proxy-generation`**: Builds a Poisson surface reconstruction and decimate/clean it using Open3D.
5. **`undistortion`**: Undistorts source images into a dense pinhole camera coordinate space.
6. **`brush-training`**: Optimizes 3D Gaussian Splats on GPU/WGPU for 30,000 steps.

---

## 3. Packaging the Scene

Use `aether-pack` to compile the reconstruction artifacts into a single `.aether` archive file. The archive packs the metadata, compressed Gaussian splats (zstd compressed PLY), and the proxy geometry.

```bash
# Compile to a canonical .aether package
./build/debug/tools/aether-pack/aether-pack \
    ./reconstruction-job/exports \
    --output scene.aether \
    --preset balanced
```

---

## 4. Performance Exit Gates

The `aether-benchmark` tool is the quality gate that verifies that rendering and computation budgets are strictly met. The gate enforces:
- **30 FPS / 60 FPS Target Latencies**: Measured as p95 frame rendering latency.
- **Memory Footprint Bounds**: Enforces peak VRAM/system memory usage limits.

### Running the Performance Gate

```bash
./build/debug/apps/AetherBenchmark/aether-benchmark \
    scene.aether \
    --camera-path ./tests/fixtures/camera-path.json \
    --width 1920 \
    --height 1080 \
    --frames 100 \
    --warmup 10 \
    --max-p95-ms 33.3 \
    --max-memory-bytes 536870912 \
    --json
```

### Diagnostic Output Example
```json
{
  "ok": true,
  "device": "Apple M2 Pro",
  "width": 1920,
  "height": 1080,
  "gpuMedianMs": 3.48,
  "gpuP95Ms": 7.32,
  "peakMetalAllocatedBytes": 40304640,
  "budgets": {
    "passed": true,
    "p95Passed": true,
    "memoryPassed": true
  }
}
```

---

## 5. Automated Verification

AETHER includes automated validation tests in its CTest suite. To run the full validation suite (including GPU rendering correctness and budget checks):

```bash
# Verify the entire suite passes on the local machine
BypassSandbox=true ctest --test-dir build/debug -V
```
