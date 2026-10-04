# Maveb sensor-alignment contract

The sensor-alignment boundary maps an arbitrary-scale COLMAP camera rig into the metric world of an
exported iPad LiDAR capture. It does not infer which images correspond. The input normalizer or a
reviewed user mapping must provide those identities explicitly.

## Match schema v1

```json
{
  "schemaVersion": 1,
  "pairs": [
    {"colmapImage": "ipad/frame-000001.jpg", "captureFrameId": 1},
    {"colmapImage": "ipad/frame-000009.jpg", "captureFrameId": 9}
  ]
}
```

`colmapImage` is the exact safe relative name in COLMAP `images.txt`. `captureFrameId` is the stable
frame identity in the finalized `.mavebcapture/manifest.json`. Both columns must be unique. Absolute
paths, traversal, duplicate images, duplicate frame IDs, unknown images, and unknown capture frames
are rejected.

## Coordinate and estimator contract

- Source: COLMAP arbitrary-scale world; image camera axes are `+X right, +Y down, +Z forward`.
- Target: MavebCapture metric world after desktop replay converts ARKit camera axes to the same
  image-aligned convention.
- Transform: `target = scale * rotate(source) + translation`, with a positive bounded scale and a
  `(w,x,y,z)` unit quaternion.
- Fit: deterministic three-camera RANSAC followed by Huber-weighted consensus refinement.
- Inliers: both metric camera-center error and camera-orientation error must clear configured gates.
- Degeneracy: fewer than the required consensus, collinear motion, invalid quaternions, and invalid
  scale fail without producing a successful camera rig.

The output schema v1 records content hashes for COLMAP `images.txt`, the finalized capture manifest,
and the match file; the seed and recovered Sim(3); all quality metrics and issues; each match's
residual/inlier status; and every COLMAP camera transformed into metric world coordinates. A
mathematically fitted transform may still be written with `accepted: false` for diagnostics, and the
CLI exits non-zero in that case. `--dry-run` performs capture hash verification and fitting without
replacing the requested output.

## Capture workflow

1. Record a slow, non-collinear orbit with MavebCapture and export the finalized package.
2. Include selected iPad RGB frames with the Sony images in one COLMAP reconstruction.
3. Preserve the input-normalizer mapping from each derived iPad image to its capture frame ID.
4. Run `maveb-align-sensors` and require an accepted metric residual report.
5. Use `metricCameras` for Sony texture projection and the recovered Sim(3) for geometry/point data.

Physical paired-capture E3 evidence remains mandatory before this becomes a product-quality claim.
