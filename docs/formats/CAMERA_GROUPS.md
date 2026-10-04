# Camera-group manifest v1

`aether-reconstruct --input-kind multi-camera` requires a JSON manifest so incompatible camera
intrinsics are never merged by filename guesswork. Each selected image must be stored directly
inside exactly one declared child folder below the reconstruction image root.

```json
{
  "schemaVersion": 1,
  "groups": [
    {
      "id": "sony-a7v-35mm",
      "relativeDirectory": "sony",
      "device": "Sony Alpha 7 V",
      "lens": "FE 28-70mm F3.5-5.6 OSS",
      "focalLengthMillimetres": 35,
      "calibrationId": "sony-a7v-35mm-v1"
    },
    {
      "id": "ipad-wide",
      "relativeDirectory": "ipad",
      "device": "iPad Pro 11-inch 3rd generation",
      "lens": "wide",
      "calibrationId": "ipad-wide-v1"
    }
  ]
}
```

Required group fields are `id`, `relativeDirectory`, `device`, and `lens`. `calibrationId` is
optional but should identify the calibration artifact used for a measured setup.
`focalLengthMillimetres` is optional and must be positive when present. IDs and directories must be
unique; absolute paths, `..`, root-level groups, empty groups, uncovered images, and nested image
paths are rejected.

Directory structure:

```text
dataset/images/
  sony/
    frame_000001.jpg
    frame_000002.jpg
  ipad/
    frame_000001.jpg
```

For a zoom lens, lock focal length during one sequence. If focal length changes materially, split
the frames into separately calibrated folders/groups. This contract preserves camera identity for
COLMAP; it does not itself align ARKit metric poses or LiDAR depth to the Sony reconstruction.
