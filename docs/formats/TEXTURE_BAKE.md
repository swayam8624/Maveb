# Maveb metric texture-bake contract

`maveb-texture-bake` turns validated metric geometry and registered camera evidence into one
self-contained textured GLB. Inputs are untrusted and bounded.

```text
metric triangle PLY
+ COLMAP cameras.txt
+ accepted metric-camera-rig.json
+ exact registered images
-> visibility/exposure-aware texture atlas
-> native GLB + GLB.provenance.json
```

Camera image names are safe paths relative to `--images`. Decoded dimensions must exactly match the
selected COLMAP calibration aspect ratio; bounded downscaling scales intrinsics by the exact image
ratio. Supported models are `SIMPLE_PINHOLE`, `PINHOLE`, `SIMPLE_RADIAL`,
`RADIAL`, and `OPENCV`; unsupported or malformed calibration is a hard error. Camera transforms use
the metric-rig convention: camera `+X` right, `+Y` down, `+Z` forward, and metric world units.

The output GLB contains duplicated vertices at UV seams, indexed triangles, normalized geometric
normals, tangents, one metallic-zero/roughness-one material, one clamped base-color texture, and an
embedded PNG. The exporter atomically replaces the GLB and then strictly reloads it. A non-dry run
also atomically writes `<output.glb>.provenance.json`; provenance failure removes the GLB rather
than leaving an apparently complete but unidentified artifact. `--dry-run` executes decode, bake,
PNG encode, GLB export, and strict reload through a temporary file without changing either final
artifact.

Coverage is the ratio of observed to attempted texels inside UV triangles. Dilated gutter pixels do
not inflate coverage. E2 fixtures prove deterministic bytes, depth rejection, exposure matching,
structured failure, input hashes, dry-run isolation, and strict GLB round-trip. They do not replace
the real Sony/iPad E3 gate.
