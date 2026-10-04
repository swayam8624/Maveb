# 2026-08-11 metric and textured mesh evidence

This record upgrades two offline reconstruction paths to E3 using downloaded real-world public
data. Generated datasets and raw run directories remain ignored; the commands and measured results
below are the reproducible handoff, not release performance claims.

## Environment

- Apple M2 Pro, 32 GB unified memory, macOS 26.5 SDK / Xcode 26.6.
- Source base before this uncommitted tranche: `93e4895e669baa53c09a06199253afb1a0c847f4`.
- Pinned Open3D/NumPy evaluation environment under `.aether-deps/proxy-venv`.
- Apple `PhotogrammetrySession` through RealityKit and Blender 5.2.0 LTS.

## ARKitScenes known-pose RGB-D

The adapter maps the official ARKitScenes world-to-camera trajectory into schema-v2 native ARKit
axes. Desktop replay converts that to AETHER's image-aligned `+Y down, +Z forward` convention.
Automatic bounds are estimated from valid metric depth before a second replay performs real TSDF
integration.

Thirty-frame command (24 frames synchronized):

```bash
./tools/run-mavebbench.zsh run arkitscenes-47333462 \
  --run-id arkit-30-oracle --force --arkit-stride 6 --arkit-max-frames 30 \
  --arkit-max-axis 96 --arkit-bounds-stride 8 --arkit-voxel 0.02 \
  --arkit-padding 0.08 --geometry-max-points 100000
```

Observed output:

- Volume origin `[-0.307325, -0.420252, -0.667690]`, dimensions `38 x 46 x 11`.
- 20 mm voxels and 80 mm truncation.
- 2,151 vertices and 4,146 triangles with integrated color.
- Accuracy median 18.35 mm, p95 29.19 mm.
- Candidate-bounds completeness median 15.85 mm, p95 62.59 mm.
- Symmetric mean Chamfer 20.21 mm.
- F-score 0.613 at 20 mm and 0.943 at 50 mm.
- Unoriented normal error median 3.01 degrees and p95 29.00 degrees.

The completeness region is explicitly the candidate AABB plus 50 mm: 913 of 100,000 sampled
reference points. It is local partial-sequence evidence, not a whole-room completeness result.

The 100-frame configuration synchronized 94 frames and produced 30,293 vertices / 58,756 triangles.
The bounded 128-axis grid increased its voxel size to 30.79 mm; accuracy median became 23.42 mm and
F-score at 50 mm became 0.780. This measured resolution loss is the justification for sparse-volume
R5 work.

## RGB video textured mesh

The first sorted uCO3D object video was sampled deterministically at 2 fps into 74 validated
1080x1920 frames. Both Apple artifacts preserve checkpoint state and a JSON manifest containing all
input SHA-256 hashes.

```bash
./tools/run-mavebbench.zsh run uco3d-object --run-id photogrammetry-medium \
  --force --skip-reconstruction --photogrammetry \
  --photogrammetry-detail medium --convert-glb --video-fps 2
```

The medium run produced:

- A 28 MB textured USDZ containing a baked mesh, diffuse texture, normal texture, and ambient
  occlusion texture.
- A 27 MB binary glTF produced by the background Blender adapter.
- Successful Blender re-import with 29,534 vertices, 50,006 polygons, material assignments, and
  embedded images.

The preview preset also completed, producing a 2.0 MB USDZ and 2.07 MB GLB with 14,820 vertices and
25,005 polygons. These establish fast and quality baselines; neither substitutes for the future
metric LiDAR/Sony registration and texture-projection path.

## Remaining limitations

- The dense TSDF grid trades spatial resolution for bounded memory as scene extent increases.
- The ARKit slice uses known recorded poses; it does not prove RGB visual odometry or live capture.
- Candidate-bounds reference cropping must stay visible in every partial-sequence report.
- Apple photogrammetry is a macOS platform dependency and its USDZ is preserved as the source of
  truth before optional Blender conversion.
- Cross-device metric alignment, confidence-aware mesh cleanup, and Sony texture reprojection await
  the paired recording supplied by the project owner.
