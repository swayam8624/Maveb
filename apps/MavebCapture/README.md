# MavebCapture

`MavebCapture` is the iPadOS LiDAR recording companion. It records bounded, native ARKit data
instead of exporting only ARKit's preview mesh:

- bi-planar YUV camera planes;
- metric scene depth and confidence;
- image- and depth-resolution intrinsics;
- camera-to-world transforms and tracking state;
- AR timestamps plus monotonic host timestamps frozen at the ARSession callback;
- exposure metadata, hashes, an append-only frame journal, and atomic manifests.

During recording, completed plane sets are committed to `frames.ndjson` and a constant-size
`checkpoint.json`; the growing canonical manifest is not rewritten for every frame. A clean stop
compacts the journal into `manifest.json`. After an interruption or process termination, reopening
MavebCapture verifies each journaled plane path, byte count, and SHA-256, ignores only a torn final
record, finalizes the recovered manifest, and exposes the package for export.

Frame admission is motion- and quality-aware rather than a fixed timer. It accepts a maximum of
15 useful frames per second while moving, refreshes a stationary view at 2 Hz, and filters redundant
poses, nearly fully clipped images, unusably soft images, low-confidence depth, and frames admitted
while the bounded writer is already under pressure. The UI reports accepted, filtered, and
queue-dropped counts separately.

Configure a signing-free compile check:

```bash
cmake -S apps/MavebCapture -B build/ipad-capture -G Xcode \
  -DCMAKE_SYSTEM_NAME=iOS \
  -DCMAKE_OSX_DEPLOYMENT_TARGET=17.0

cmake --build build/ipad-capture --config Debug \
  -- -sdk iphoneos CODE_SIGNING_ALLOWED=NO
```

For a device build, add the Apple ID owning the development certificate under **Xcode → Settings →
Accounts**, then open `build/ipad-capture/MavebCapture.xcodeproj`, select that development team and
the connected LiDAR iPad, and Run. Device identifiers and signing credentials are never stored in
the repository.

The app writes each completed `.mavebcapture` directory under **On My iPad → Maveb Capture →
Captures**. Export that directory through Files or the app's Share button and run:

```bash
build/debug/tools/aether-fuse/aether-fuse Scan.mavebcapture \
  --output scan-proxy.ply \
  --origin -1.5 -1.5 -1.5 \
  --dimensions 300 300 300 \
  --voxel 0.01 \
  --truncation 0.04
```
