# Canonical Asset v1

Canonical Asset v1 is the first common output contract for Maveb reconstruction providers. It
separates the high-quality editable surface from the proxy used for rendering depth, collision, or
navigation. Apple Object Capture, future sparse fusion, Sony+iPad alignment, texture baking, and
residual appearance must all target the same metric frame rather than producing unrelated assets.

## Directory profile

An unpacked canonical scene contains:

```text
scene/
  metadata.json
  canonical-asset.json
  canonical.glb
  cameras.json
  confidence.bin       # only for per-vertex confidence
  proxy.ply            # optional and semantically distinct
  base-gaussians.ply   # optional appearance representation
```

The mesh must be a glTF 2 GLB with embedded buffers and images. External file and network URIs are
rejected so the bytes validated and hashed by the packer are exactly the bytes placed in `.aether`.
The mesh is interpreted in metres using a right-handed, Y-up frame with camera forward along `-Z`.

`canonical-asset.json` is:

```json
{
  "schemaVersion": 1,
  "name": "Measured tabletop object",
  "coordinateSystem": "right-handed-y-up-negative-z-forward",
  "metersPerUnit": 1.0,
  "mesh": "canonical.glb",
  "cameras": "cameras.json",
  "confidence": {"kind": "uniform", "value": 0.8},
  "geometryProvider": {
    "name": "apple-photogrammetry",
    "version": "macOS-build-and-tool-version",
    "inputSha256": "64 non-zero hexadecimal characters",
    "configurationSha256": "64 non-zero hexadecimal characters"
  },
  "appearanceProvider": {
    "name": "apple-photogrammetry-texture",
    "version": "macOS-build-and-tool-version",
    "inputSha256": "64 non-zero hexadecimal characters",
    "configurationSha256": "64 non-zero hexadecimal characters"
  }
}
```

Confidence may instead use `{"kind":"per-vertex","file":"confidence.bin"}`. That file must
already use the `AETHCF` codec and contain exactly one finite float32 value in `[0,1]` for every
loaded mesh vertex. Uniform confidence is expanded into the same canonical chunk during packing;
there is no implicit “unknown means one” behavior.

## Camera schema

`cameras.json` contains a bounded array of calibrated observations:

```json
{
  "schemaVersion": 1,
  "cameras": [{
    "id": "sony-000001",
    "sourceId": "sony-a7v-28-70mm-session-1",
    "image": "sony/000001.jpg",
    "width": 7008,
    "height": 4672,
    "intrinsics": [5000.0, 5000.0, 3504.0, 2336.0],
    "cameraToWorld": [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1],
    "timestampNanoseconds": 42,
    "confidence": 0.95
  }]
}
```

Transforms are column-major rigid camera-to-world matrices in the canonical frame. Camera IDs and
image paths must be unique. Intrinsics are `[fx, fy, cx, cy]` in pixels at the declared resolution.
The optional timestamp retains source time; confidence is mandatory and must be in `[0,1]`.

During packing JSON is converted to the deterministic `AETHCAM` binary chunk. Records retain the
camera ID, source ID, image identity, dimensions, intrinsics, pose, timestamp, and confidence.
Readers reject non-finite values, non-affine or non-rigid transforms, reflection matrices, invalid
string offsets, duplicates, hostile paths, size mismatches, and non-zero reserved fields.

## Evidence boundary

Canonical Asset v1 is E2 contract evidence: fixtures prove deterministic encoding, validation,
packaging without Gaussians, semantic inspection, and backward compatibility. It does not prove
that current Sony and iPad captures are aligned, that the mesh has metric accuracy, or that texture
quality is acceptable. Those claims require a real paired capture, robust Sim(3) alignment, surface
metrics, and held-out rendering evidence.
