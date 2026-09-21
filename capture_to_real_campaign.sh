#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

usage() {
  cat <<'EOF'
Usage:
  ./capture_to_real_campaign.sh /absolute/path/Scan.mavebcapture

Takes one real MavebCapture LiDAR recording and performs:
  capture validation/fusion -> metric proxy PLY
  -> deterministic spatial Gaussian world seeding
  -> .aetherworld + Gaussian/ownership sidecars
  -> frozen real CBRC campaign
  -> baselines/ablations/oracle/paper artifacts

Optional environment:
  MAVEB_CAPTURE_OUT=/absolute/path/output
  MAVEB_CAPTURE_VOXEL=0.01
  MAVEB_CAPTURE_TRUNCATION=0.04
  MAVEB_CAPTURE_MAX_AXIS=320
  MAVEB_CAPTURE_SAMPLE_STRIDE=4
  MAVEB_CAPTURE_PADDING=0.08
  MAVEB_SEED_CELL_SIZE=0.0       # 0 = derive from scene extent
  MAVEB_SEED_GAUSSIAN_SCALE=0.0 # 0 = derive from scene extent/density
  MAVEB_WORK_COST=/path/to/frozen-work-cost.json
EOF
}

if [[ $# -ne 1 || "$1" == "--help" || "$1" == "-h" ]]; then
  usage
  [[ $# -eq 1 ]] && exit 0
  exit 2
fi

CAPTURE="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
[[ -d "$CAPTURE" ]] || {
  echo "Capture directory not found: $CAPTURE" >&2
  exit 2
}
[[ -f "$CAPTURE/manifest.json" ]] || {
  echo "Capture is missing manifest.json: $CAPTURE" >&2
  exit 2
}

OUT="${MAVEB_CAPTURE_OUT:-$ROOT/build/real-capture-bootstrap}"
PROXY="$OUT/real-proxy.ply"
WORLD="$OUT/real-seeded.aetherworld"
FUSE="$ROOT/build/ci/tools/aether-fuse/aether-fuse"
SEED="$ROOT/build/ci/tools/maveb-seed-world/maveb-seed-world"

VOXEL="${MAVEB_CAPTURE_VOXEL:-0.01}"
TRUNCATION="${MAVEB_CAPTURE_TRUNCATION:-0.04}"
MAX_AXIS="${MAVEB_CAPTURE_MAX_AXIS:-320}"
SAMPLE_STRIDE="${MAVEB_CAPTURE_SAMPLE_STRIDE:-4}"
PADDING="${MAVEB_CAPTURE_PADDING:-0.08}"
CELL_SIZE="${MAVEB_SEED_CELL_SIZE:-0}"
GAUSSIAN_SCALE="${MAVEB_SEED_GAUSSIAN_SCALE:-0}"

mkdir -p "$OUT"

echo "============================================================"
echo "MAVEB real capture -> persistent world -> CBRC campaign"
echo "============================================================"
echo "Capture : $CAPTURE"
echo "Output  : $OUT"
echo "Git SHA : $(git rev-parse HEAD)"
echo

echo "==> [1/5] Building real-capture tools"
cmake --preset ci
cmake --build --preset ci --target aether-fuse maveb-seed-world   maveb-cbrc-revision maveb-cbrc-gaussian-oracle --parallel

echo "==> [2/5] Validating and fusing real LiDAR capture"
"$FUSE" "$CAPTURE"   --output "$PROXY"   --auto-bounds   --voxel "$VOXEL"   --truncation "$TRUNCATION"   --max-axis "$MAX_AXIS"   --sample-stride "$SAMPLE_STRIDE"   --padding "$PADDING"   --json | tee "$OUT/fusion.json"

[[ -s "$PROXY" ]] || {
  echo "Fusion did not produce a proxy PLY: $PROXY" >&2
  exit 3
}

echo "==> [3/5] Seeding a persistent Gaussian world from real geometry"
SEED_ARGS=(
  --proxy "$PROXY"
  --output "$WORLD"
  --json
)
if [[ "$CELL_SIZE" != "0" ]]; then
  SEED_ARGS+=(--cell-size "$CELL_SIZE")
fi
if [[ "$GAUSSIAN_SCALE" != "0" ]]; then
  SEED_ARGS+=(--gaussian-scale "$GAUSSIAN_SCALE")
fi

"$SEED" "${SEED_ARGS[@]}" | tee "$OUT/world-seed.json"

[[ -s "$WORLD" ]] || {
  echo "World seeding did not produce: $WORLD" >&2
  exit 4
}
[[ -s "$WORLD.gaussians.r1.bin" ]] || {
  echo "World seeding did not produce Gaussian sidecar" >&2
  exit 4
}
[[ -s "$WORLD.ownership.r1.bin" ]] || {
  echo "World seeding did not produce ownership sidecar" >&2
  exit 4
}

echo "==> [4/5] Running frozen real CBRC campaign"
MAVEB_REAL_ARCHIVE="$WORLD" MAVEB_REAL_RESULTS_DIR="$OUT/cbrc" MAVEB_WORK_COST="${MAVEB_WORK_COST:-}" "$ROOT/run_real_campaign.sh"

echo "==> [5/5] Final result"
echo "World         : $WORLD"
echo "Proxy         : $PROXY"
echo "World seed    : $OUT/world-seed.json"
echo "Campaign      : $OUT/cbrc/campaign/REAL_CAMPAIGN_ANSWER.md"
echo "Paper figures : $OUT/cbrc/campaign/paper-artifacts"
echo
echo "REAL CAPTURE PIPELINE COMPLETE."
