#!/bin/zsh
set -euo pipefail

fuser="$1"
root="$2"
rm -rf "$root"
mkdir -p "$root"

: > "$root/color.raw"
: > "$root/depth.f32"
for _ in {1..64}; do
  printf '\x80\x80\x80' >> "$root/color.raw"
  printf '\x00\x00\x80\x3f' >> "$root/depth.f32"
done

cat > "$root/manifest.json" <<'JSON'
{
  "schemaVersion": 1,
  "sourceId": "oracle-cli-fixture",
  "calibration": {
    "width": 8,
    "height": 8,
    "fx": 8.0,
    "fy": 8.0,
    "cx": 3.5,
    "cy": 3.5
  },
  "frames": [
    {
      "frameId": 1,
      "timestampNs": 1,
      "color": "color.raw",
      "depth": "depth.f32",
      "orientation": [1.0, 0.0, 0.0, 0.0],
      "translation": [0.0, 0.0, 0.0]
    }
  ]
}
JSON

"$fuser" "$root" --output "$root/proxy.ply" \
  --origin -0.2 -0.2 0.8 --dimensions 9 9 9 --voxel 0.05 --truncation 0.1 --json
test -s "$root/proxy.ply"
head -c 3 "$root/proxy.ply" | grep -q ply

"$fuser" "$root" --output "$root/nested/proxy-auto.ply" \
  --auto-bounds --max-axis 32 --sample-stride 2 --voxel 0.02 --padding 0.1 --json
test -s "$root/nested/proxy-auto.ply"
head -c 3 "$root/nested/proxy-auto.ply" | grep -q ply
