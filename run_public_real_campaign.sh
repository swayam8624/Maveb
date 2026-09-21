#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON="${MAVEB_PYTHON:-$ROOT/.venv-maveb/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="${MAVEB_PYTHON:-python3}"
fi

OUT="${MAVEB_PUBLIC_RESULTS_DIR:-$ROOT/build/public-real-campaign}"
SOURCE="$OUT/source"
WORLDS="$OUT/worlds"
FROZEN="$OUT/frozen-inputs"
RESULTS="$OUT/campaign"
MANIFEST="$ROOT/research/config/cbrc_public_real_sources.json"
ORACLE="$ROOT/build/ci/tools/maveb-cbrc-gaussian-oracle/maveb-cbrc-gaussian-oracle"
REVISION="$ROOT/build/ci/tools/maveb-cbrc-revision/maveb-cbrc-revision"

mkdir -p "$SOURCE" "$WORLDS" "$FROZEN" "$RESULTS"

echo "============================================================"
echo "MAVEB public real RGB/COLMAP CBRC campaign"
echo "============================================================"
echo "Repository : $ROOT"
echo "Git SHA    : $(git rev-parse HEAD)"
echo "Output     : $OUT"
echo "Input      : pinned public Tanks & Temples RGB-derived COLMAP"
echo "User data  : NONE"
echo

FETCH_ARGS=(
  --manifest "$MANIFEST"
  --output-dir "$SOURCE"
)
if [[ -n "${MAVEB_PUBLIC_ARCHIVE:-}" ]]; then
  FETCH_ARGS+=(--archive "$MAVEB_PUBLIC_ARCHIVE")
fi

echo "==> [1/6] Fetching and verifying pinned public dataset"
"$PYTHON" benchmarks/scripts/cbrc_fetch_public_dataset.py "${FETCH_ARGS[@]}"

SOURCE_ID="$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["sourceId"])'   "$SOURCE/PUBLIC_SOURCE_PROVENANCE.json")"
SOURCE_URL="$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["url"])'   "$SOURCE/PUBLIC_SOURCE_PROVENANCE.json")"
ARCHIVE_SHA="$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["archiveSha256"])'   "$SOURCE/PUBLIC_SOURCE_PROVENANCE.json")"

echo "==> [2/6] Seeding native MAVEB worlds from ordinary-RGB SfM"
for SCENE in tandt-train tandt-truck; do
  MODEL="$SOURCE/extracted/$SCENE/sparse/0"
  WORLD="$WORLDS/$SCENE.aetherworld"
  "$PYTHON" benchmarks/scripts/cbrc_seed_colmap_world.py     --model-dir "$MODEL"     --output "$WORLD"     --scene-id "$SCENE"     --source-id "$SOURCE_ID"     --source-url "$SOURCE_URL"     --archive-sha256 "$ARCHIVE_SHA"     > "$WORLDS/$SCENE.seed.json"
done

echo "==> [3/6] Building independent production/oracle tools"
if [[ ! -x "$ORACLE" || ! -x "$REVISION" ]]; then
  cmake --preset ci
  cmake --build --preset ci --target     maveb-cbrc-revision     maveb-cbrc-gaussian-oracle     --parallel
fi

echo "==> [4/6] Freezing public real revision campaign before results"
PREP_ARGS=(
  --output-dir "$FROZEN"
  --search-root "$WORLDS"
  --max-depth 3
)
if [[ -n "${MAVEB_WORK_COST:-}" ]]; then
  [[ -f "$MAVEB_WORK_COST" ]] || {
    echo "MAVEB_WORK_COST does not exist: $MAVEB_WORK_COST" >&2
    exit 3
  }
  PREP_ARGS+=(--work-cost-model "$MAVEB_WORK_COST")
fi
"$PYTHON" benchmarks/scripts/cbrc_prepare_real_campaign.py "${PREP_ARGS[@]}"

echo "==> [5/6] Running CBRC, independent oracle, baselines, ablations and parity"
set +e
"$PYTHON" benchmarks/scripts/cbrc_campaign.py   --campaign "$FROZEN/campaign.json"   --oracle "$ORACLE"   --revision-tool "$REVISION"   --git-sha "$(git rev-parse HEAD)"   --output-dir "$RESULTS"
CAMPAIGN_STATUS=$?
set -e

echo "==> [6/6] Producing answer-first evidence report"
set +e
"$PYTHON" research/analysis/cbrc_real_campaign_report.py   --results-dir "$RESULTS"
REPORT_STATUS=$?
set -e

cat <<EOF

Public source provenance : $SOURCE/PUBLIC_SOURCE_PROVENANCE.json
Seeded worlds            : $WORLDS
Frozen campaign          : $FROZEN/campaign.json
Freeze hashes            : $FROZEN/campaign-freeze.json
Campaign gates           : $RESULTS/campaign-gates.json
Baseline summary         : $RESULTS/baseline-summary.json
Answer                   : $RESULTS/REAL_CAMPAIGN_ANSWER.md
Paper artifacts          : $RESULTS/paper-artifacts

Scientific boundary:
  * real ordinary-RGB-derived COLMAP geometry/color
  * NO LiDAR and NO private/user-provided data
  * global metric scale is canonicalized, not measured
  * Gaussians are SfM-seeded, not photorealistically trained 3DGS
EOF

if (( CAMPAIGN_STATUS != 0 )); then
  echo "PUBLIC REAL CAMPAIGN FAILED EVIDENCE GATES (exit $CAMPAIGN_STATUS)." >&2
  exit "$CAMPAIGN_STATUS"
fi
if (( REPORT_STATUS != 0 )); then
  echo "PUBLIC REAL CAMPAIGN REPORT MARKS EVIDENCE AS FAILED." >&2
  exit "$REPORT_STATUS"
fi

echo
echo "PUBLIC REAL RGB/COLMAP CAMPAIGN PASSED."
