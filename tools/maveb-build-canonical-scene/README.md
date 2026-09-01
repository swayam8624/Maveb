# maveb-build-canonical-scene

Builds the deterministic Canonical Asset v1 scene directory used by the Maveb v0.1 captured-world release.

The tool deliberately consumes only already-frozen artifacts: a metric TSDF proxy, C1.3 geometry evidence, a metric textured GLB and its `maveb-texture-bake` provenance, Brush base Gaussians, an accepted `maveb-align-sensors` metric rig, the immutable `.mavebcapture`, and the frozen image/frame correspondence file.

It performs four correctness-sensitive operations:

1. Verifies provenance hashes across capture, proxy, metric rig, camera matches, texture bake, and GLB.
2. Applies the accepted COLMAP-to-metric Sim(3) to Gaussian positions, anisotropic orientation, log-scales, and the standard degree-3 GraphDECO real-SH coefficients used by Maveb.
3. Builds Canonical Asset v1 `cameras.json` from recorded schema-v2 image intrinsics plus the accepted metric poses, converting camera-local `+Y down,+Z forward` into canonical `+Y up,-Z forward`.
4. Emits a directly packable scene directory containing `metadata.json`, `canonical-asset.json`, `canonical.glb`, `cameras.json`, `proxy.ply`, `base-gaussians.ply`, and `canonicalization.json`.

The uniform canonical confidence is the global fraction of frozen ARKit confidence pixels with code >= medium. Each camera's confidence is the same statistic computed only for its matched capture frame. These are acquisition summaries and are explicitly not new research claims.

## Usage

```bash
maveb-build-canonical-scene \
  --proxy /path/to/reference-proxy.ply \
  --geometry-evidence benchmarks/evidence/reference-world-v1-proxy-reconstruction.json \
  --textured-glb /path/to/reference-canonical.glb \
  --texture-provenance /path/to/reference-canonical.glb.provenance.json \
  --gaussians /path/to/base-gaussians.ply \
  --metric-rig /path/to/metric-camera-rig.json \
  --capture /path/to/reference.mavebcapture \
  --camera-matches /path/to/camera-matches.json \
  --output /path/to/scene \
  --name "Maveb Reference Desk Corner v1" \
  --json
```

The destination must not already exist. Construction happens in a sibling temporary directory and is published only after all outputs are complete and hashed.
