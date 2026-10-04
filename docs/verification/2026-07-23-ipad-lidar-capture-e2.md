# iPad LiDAR capture and replay — E2

Date: 2026-07-23

This evidence is E2 fixture evidence, not a real-scene reconstruction claim.

## Implemented

- `MavebCapture` builds as a Swift 6 iPadOS 17+ application against the physical-device SDK.
- ARKit world tracking supplies camera YUV, metric scene depth, confidence, intrinsics, pose,
  exposure, and timestamps.
- Recording accepts only normal-tracking frames with scene depth, samples at 10 Hz, bounds pending
  writes to three frames, reports drops/failures, and writes atomic schema-v2 manifests.
- Each plane preserves its native stride and has a byte count and SHA-256 digest.
- Desktop replay validates schema-v2 structure, ordering, paths, dimensions, strides, hashes,
  calibration, tracking state, coordinate conversion, and confidence normalization.
- TSDF color integration consumes the two YUV planes and maps depth pixels to color resolution.

## Verification

```text
Unsigned iPhoneOS SDK build: succeeded
macOS debug build: succeeded
CTest debug: 15/15 passed
Schema-v2 fixture: replay, axis conversion, confidence normalization, checksum rejection
```

The connected iPad reports Developer Mode enabled and supports installation. A valid local Apple
Development identity exists, but Xcode has no signed-in account/provisioning profile for its team.
On-device installation and a real scan therefore remain E3 user-gated work.

## Next evidence

1. Add the owning Apple ID under Xcode Settings → Accounts.
2. Install and launch MavebCapture on the LiDAR iPad.
3. Record a small matte tabletop object from a slow closed orbit.
4. Transfer the `.mavebcapture` directory and run `aether-fuse`.
5. Record the capture provenance, fusion configuration, mesh metrics, and a 30-minute capture soak.
