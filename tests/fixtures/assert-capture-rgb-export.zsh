#!/bin/zsh
set -euo pipefail

exporter="$1"
validator="$2"
root="$3"

rm -rf "$root"
mkdir -p "$root/capture/color" "$root/capture/depth" "$root/capture/confidence"

printf '\x10\x40\x80\xeb' > "$root/capture/color/000001.y8"
printf '\x80\x80' > "$root/capture/color/000001.cbcr8x2"
printf '\x00\x00\x80\x3f\x00\x00\x80\x3f\x00\x00\x80\x3f\x00\x00\x80\x3f' > "$root/capture/depth/000001.f32"
printf '\x00\x01\x02\x02' > "$root/capture/confidence/000001.u8"

cat > "$root/capture/manifest.json" <<'JSON'
{
  "schemaVersion": 2,
  "sourceID": "ipad-lidar-rgb-export-fixture",
  "coordinateSystem": {
    "camera": "ARKit right-handed: +X right, +Y up, -Z forward",
    "pose": "column-major camera-to-world 4x4 matrix",
    "depthUnit": "metres",
    "intrinsics": "3x3 column-major pixels"
  },
  "frames": [{
    "frameID": 1,
    "arTimestampSeconds": 0.0000015,
    "hostTimestampNanoseconds": 2000,
    "nativeImageOrientation": "landscapeRight",
    "mirrored": false,
    "cameraTrackingState": "normal",
    "cameraToWorld": [1,0,0,0, 0,1,0,0, 0,0,1,0, 1,2,3,1],
    "calibration": {
      "imageWidth": 2, "imageHeight": 2, "depthWidth": 2, "depthHeight": 2,
      "imageIntrinsics": [2,0,0, 0,2,0, 0.5,0.5,1],
      "depthIntrinsics": [2,0,0, 0,2,0, 0.5,0.5,1]
    },
    "luma": {
      "path": "color/000001.y8",
      "sha256": "c9630c3201527b5af73017cb113368f7cbc7d0d5310b78c3dfb4db3462afee30",
      "width": 2, "height": 2, "rowStrideBytes": 2,
      "pixelFormat": "y8", "byteCount": 4
    },
    "chroma": {
      "path": "color/000001.cbcr8x2",
      "sha256": "af472cf2977dbfccc45851e12525627fc9ecc03f274f108a865b18a672f38ba6",
      "width": 1, "height": 1, "rowStrideBytes": 2,
      "pixelFormat": "cbcr8x2", "byteCount": 2
    },
    "depth": {
      "path": "depth/000001.f32",
      "sha256": "f6bb1294da2f78cd935b01c7656280df5eaa0439e9d97bc03775825a41a508e4",
      "width": 2, "height": 2, "rowStrideBytes": 8,
      "pixelFormat": "depth-f32-metres", "byteCount": 16
    },
    "confidence": {
      "path": "confidence/000001.u8",
      "sha256": "69aa81d76a2198545225f9bec4a345cfac7141bf4ca24de6a71ea7854a943305",
      "width": 2, "height": 2, "rowStrideBytes": 2,
      "pixelFormat": "arkit-confidence-u8", "byteCount": 4
    },
    "exposure": {"durationSeconds": 0.008, "exposureOffsetEV": 0}
  }]
}
JSON

"$exporter" "$root/capture" --output "$root/export-a" --json > "$root/export-a.json"
"$exporter" "$root/capture" --output "$root/export-b" --json > "$root/export-b.json"

test -s "$root/export-a/frame-000001.png"
test -s "$root/export-a/rgb-export.json"
cmp "$root/export-a/frame-000001.png" "$root/export-b/frame-000001.png"
cmp "$root/export-a/rgb-export.json" "$root/export-b/rgb-export.json"

"$validator" validate "$root/export-a" --minimum-images 1 --json > "$root/validation.json"
grep -q '"valid":true' "$root/validation.json"
grep -q '"frameCount": 1' "$root/export-a/rgb-export.json"
grep -q '"frameID":1' "$root/export-a/rgb-export.json"
grep -q '"pixelTransform": "none; native recorded pixel order preserved"' "$root/export-a/rgb-export.json"

png_sha="$(shasum -a 256 "$root/export-a/frame-000001.png" | awk '{print $1}')"
grep -q "$png_sha" "$root/export-a/rgb-export.json"

if "$exporter" "$root/capture" --output "$root/export-a" --json >/dev/null 2>&1; then
    echo "exporter unexpectedly overwrote an existing output directory" >&2
    exit 1
fi
