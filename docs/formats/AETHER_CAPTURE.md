# Maveb recorded capture schemas

An unpacked capture is a directory containing `manifest.json` plus immutable raw plane files.
Paths are relative to the capture root; absolute paths and `..` traversal are rejected.

```json
{
  "schemaVersion": 1,
  "sourceId": "tabletop-oracle-01",
  "calibration": {
    "width": 640,
    "height": 480,
    "fx": 525.0,
    "fy": 525.0,
    "cx": 319.5,
    "cy": 239.5
  },
  "frames": [
    {
      "frameId": 1,
      "timestampNs": 1000000000,
      "color": "color/000001.rgb8",
      "depth": "depth/000001.f32",
      "confidence": "confidence/000001.u8",
      "orientation": [1.0, 0.0, 0.0, 0.0],
      "translation": [0.0, 0.0, 0.0]
    }
  ]
}
```

## Plane formats

- Color is tightly packed RGB8 with exactly `width × height × 3` bytes.
- Depth is tightly packed native little-endian float32 metres with exactly
  `width × height × 4` bytes.
- Optional confidence is uint8 with exactly `width × height` bytes; 0 is rejected and 255 is full
  integration weight.
- Quaternions use `(w, x, y, z)`.
- Poses transform camera coordinates into world coordinates.
- Camera coordinates use +Z forward.
- Frame IDs must strictly increase; timestamps must be monotonic.

The loader bounds frame counts, dimensions, per-plane bytes, path traversal, and exact file sizes
before allocation. Schema v1 remains the deterministic oracle/development form.

## Schema v2: MavebCapture LiDAR

The iPad companion writes a `.mavebcapture` directory. Each accepted frame contains:

- native full-resolution video-range bi-planar YUV (`y8` and interleaved `cbcr8x2`);
- native row strides, rather than assuming tightly packed `CVPixelBuffer` storage;
- metric float32 ARKit scene depth and optional ARKit confidence;
- image- and depth-resolution column-major intrinsics;
- a column-major ARKit camera-to-world transform;
- ARKit and monotonic host timestamps, exposure data, and tracking state;
- byte counts and SHA-256 for every plane.

Only frames with normal ARKit tracking and scene depth are recorded. The desktop loader:

- verifies paths, dimensions, strides, byte counts, formats, ordering, and hashes;
- converts ARKit's `+X right, +Y up, -Z forward` camera coordinates to Maveb's
  image-aligned `+X right, +Y down, +Z forward` convention;
- scales depth calibration at capture time and preserves it per frame;
- converts ARKit confidence levels 0/1/2 to fusion weights 0/128/255;
- retains both YUV planes and samples them at depth resolution during color integration.

Schema v2 is deliberately an unpacked, inspectable recording. Transfer the complete directory; a
single damaged or missing plane causes a structured replay error rather than partial fusion.

### In-progress recording and recovery

The host timestamp is sampled when `ARSessionDelegate` receives the frame, before any main-actor or
writer-queue delay. It therefore represents frame admission time rather than disk persistence time.

While a recording is active, `manifest.json` is a constant-size session header with an empty frame
array. A frame becomes recoverable only after all of its atomically written planes have been hashed
and its compact JSON record has been appended to `frames.ndjson` and synchronized. A small,
atomically replaced `checkpoint.json` carries counters and the last committed frame ID. This makes
recording I/O linear in frame count rather than repeatedly serializing the full history.

On a clean stop, MavebCapture writes the complete canonical `manifest.json` once and removes the
journal/checkpoint. On the next launch after an interruption, it:

1. reads complete newline-terminated journal records;
2. ignores only an incomplete final record;
3. enforces sequential frame IDs and monotonic callback timestamps;
4. rejects unsafe, duplicate, missing, size-mismatched, or hash-mismatched planes;
5. records recovery time and discarded trailing byte count; and
6. atomically compacts the recovered manifest before making it exportable.

Orphan plane files that were written without a committed journal record are never admitted.

### Frame admission

Normal tracking and scene depth remain mandatory. The capture companion then samples luma gradients,
video-range clipping, and ARKit depth confidence before applying a deterministic keyframe policy:

- no more than 15 accepted frames per second;
- accept after at least 15 mm translation or 2 degrees of view rotation;
- refresh an otherwise stationary view every 500 ms;
- reject frames when fewer than 20% of sampled depth pixels have medium/high confidence;
- reject only extreme image failures (at least 95% clipped or effectively zero sampled gradient);
- reject before enqueue when the three-frame writer ring already has three pending frames.

These thresholds are v1 capture defaults, not reconstruction-quality claims. Filtered admission and
writer overflow are separate counters so diagnostics can distinguish redundant/poor frames from
storage backpressure.

## Oracle fusion

```bash
build/debug/tools/aether-fuse/aether-fuse Scan.mavebcapture \
  --output proxy.ply \
  --origin -0.5 -0.5 0.0 \
  --dimensions 128 128 128 \
  --voxel 0.01 \
  --truncation 0.04 \
  --json
```

Use `--dry-run` to validate the manifest and volume configuration without reading every plane or
producing geometry. A normal run verifies plane hashes while replaying, integrates calibrated
depth/color, extracts the zero crossing, and atomically writes a PLY proxy accepted by
`aether-pack`.
