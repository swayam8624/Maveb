#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON="${MAVEB_PYTHON:-$ROOT/.venv-maveb/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="${MAVEB_PYTHON:-python3}"
fi

OUT="${MAVEB_PUBLIC_V2_RESULTS_DIR:-$ROOT/build/public-real-v2}"
SOURCE="$OUT/source"
WORLDS="$OUT/worlds"
CAL="$OUT/calibration"
SPARSE="$OUT/sparse-discovery"
FROZEN="$OUT/frozen-inputs"
RESULTS="$OUT/campaign"
VIS="$OUT/siggraph-visuals"
VISUAL_QUALITY="$OUT/visual-quality"
MANIFEST="$ROOT/research/config/cbrc_public_real_sources.json"

REVISION="$ROOT/build/ci/tools/maveb-cbrc-revision/maveb-cbrc-revision"
ORACLE="$ROOT/build/ci/tools/maveb-cbrc-gaussian-oracle/maveb-cbrc-gaussian-oracle"
WORK_BENCH="$ROOT/build/ci/tools/maveb-cbrc-work-bench/maveb-cbrc-work-bench"
LOCALITY_BENCH="$ROOT/build/ci/tools/maveb-gaussian-locality-bench/maveb-gaussian-locality-bench"

mkdir -p "$SOURCE" "$WORLDS" "$CAL" "$SPARSE" "$FROZEN" "$RESULTS" "$VIS" "$VISUAL_QUALITY"

echo "============================================================"
echo "MAVEB CBRC paper-grade public campaign v2"
echo "============================================================"
echo "Repository : $ROOT"
echo "Git SHA    : $(git rev-parse HEAD)"
echo "Output     : $OUT"
echo "Target     : 4 public scenes x 15 frozen revisions = 60 cases"
echo "User data  : NONE"
echo

echo "==> [1/11] Fetching/verifying four-scene public RGB/COLMAP set"
FETCH_ARGS=(--manifest "$MANIFEST" --output-dir "$SOURCE" --scene-set v2)
if [[ -n "${MAVEB_PUBLIC_ARCHIVE:-}" ]]; then
  FETCH_ARGS+=(--archive "$MAVEB_PUBLIC_ARCHIVE")
elif [[ -f "$ROOT/build/public-real-campaign/source/cache/tandt_db.zip" ]]; then
  FETCH_ARGS+=(--archive "$ROOT/build/public-real-campaign/source/cache/tandt_db.zip")
fi
"$PYTHON" benchmarks/scripts/cbrc_fetch_public_dataset.py "${FETCH_ARGS[@]}"

SOURCE_ID="$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["sourceId"])' "$SOURCE/PUBLIC_SOURCE_PROVENANCE.json")"
SOURCE_URL="$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["url"])' "$SOURCE/PUBLIC_SOURCE_PROVENANCE.json")"
ARCHIVE_SHA="$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["archiveSha256"])' "$SOURCE/PUBLIC_SOURCE_PROVENANCE.json")"

echo "==> [2/11] Seeding four persistent MAVEB worlds from ordinary-RGB SfM"
"$PYTHON" - "$SOURCE/PUBLIC_SOURCE_PROVENANCE.json" > "$OUT/scenes.tsv" <<'PY'
import json,sys
for item in json.load(open(sys.argv[1]))["scenes"]:
    print(item["sceneId"] + "\t" + item["modelDir"])
PY
while IFS=$'\t' read -r SCENE MODEL; do
  [[ -n "$SCENE" ]] || continue
  WORLD="$WORLDS/$SCENE.aetherworld"
  "$PYTHON" benchmarks/scripts/cbrc_seed_colmap_world.py     --model-dir "$MODEL"     --output "$WORLD"     --scene-id "$SCENE"     --source-id "$SOURCE_ID"     --source-url "$SOURCE_URL"     --archive-sha256 "$ARCHIVE_SHA"     > "$WORLDS/$SCENE.seed.json"
done < "$OUT/scenes.tsv"

echo "==> [3/11] Building production/oracle/calibration/sparse-index tools"
cmake --preset ci
cmake --build --preset ci --target   maveb-cbrc-revision   maveb-cbrc-gaussian-oracle   maveb-cbrc-work-bench   maveb-gaussian-locality-bench   --parallel

echo "==> [4/11] Freezing hardware work calibration"
CAL_ID="public-v2-$(uname -m)-$(git rev-parse --short=12 HEAD)"
"$WORK_BENCH"   --gaussians "${MAVEB_CAL_GAUSSIANS:-1000000}"   --publication-bytes "${MAVEB_CAL_PUBLICATION_BYTES:-268435456}"   --pixels "${MAVEB_CAL_PIXELS:-921600}"   --repeats "${MAVEB_CAL_REPEATS:-9}"   --calibration-id "$CAL_ID"   > "$CAL/calibration-rows.jsonl"
"$PYTHON" benchmarks/scripts/cbrc_calibrate_work.py   --input "$CAL/calibration-rows.jsonl"   --version "$CAL_ID"   --minimum-repeats 5   --output "$CAL/work-cost-model.json"   > "$CAL/work-cost-model.stdout.json"

echo "==> [5/11] Benchmarking sparse candidate discovery"
"$PYTHON" benchmarks/scripts/cbrc_sparse_discovery_sweep.py   --binary "$LOCALITY_BENCH"   --output-dir "$SPARSE"   --repeats "${MAVEB_SPARSE_REPEATS:-9}"

echo "==> [6/11] Freezing the 60-case campaign before reading outcomes"
rm -rf "$FROZEN"
mkdir -p "$FROZEN"
"$PYTHON" benchmarks/scripts/cbrc_prepare_campaign_v2.py   --world-root "$WORLDS"   --output-dir "$FROZEN"   --cases-per-scene "${MAVEB_V2_CASES_PER_SCENE:-15}"   --work-cost-model "$CAL/work-cost-model.json"

echo "==> [7/11] Running CBRC + FULL/EXACT/heuristics + ablations + parity"
rm -rf "$RESULTS"
mkdir -p "$RESULTS"
set +e
"$PYTHON" benchmarks/scripts/cbrc_campaign.py   --campaign "$FROZEN/campaign-v2.json"   --oracle "$ORACLE"   --revision-tool "$REVISION"   --git-sha "$(git rev-parse HEAD)"   --output-dir "$RESULTS"
CAMPAIGN_STATUS=$?
set -e

echo "==> [8/11] Evaluating held-out empirical locality baseline"
"$PYTHON" research/experiments/cbrc_empirical_heldout.py   --rows "$RESULTS/campaign-rows.jsonl"   --output "$RESULTS/empirical-heldout.json"

echo "==> [9/11] Generating answer report and SIGGRAPH visual package"
set +e
"$PYTHON" research/analysis/cbrc_real_campaign_report.py   --results-dir "$RESULTS"
REPORT_STATUS=$?
set -e
"$PYTHON" research/visualization/cbrc_siggraph_visuals.py   --campaign-dir "$RESULTS"   --output-dir "$VIS"   --max-mosaic-cases 20

echo "==> [10/11] Measuring selected-repair visual fidelity against FULL-after"
"$PYTHON" research/analysis/cbrc_visual_quality.py \
  --campaign-dir "$RESULTS" \
  --output-dir "$VISUAL_QUALITY"

echo "==> [11/11] Paper-readiness audit"
"$PYTHON" research/analysis/cbrc_paper_readiness.py   --campaign-dir "$RESULTS"   --calibration "$CAL/work-cost-model.json"   --sparse-summary "$SPARSE/sparse-discovery-summary.json"   --empirical "$RESULTS/empirical-heldout.json"   --visual-package "$VIS/VISUAL_PACKAGE.json"   --visual-quality "$VISUAL_QUALITY/CBRC_VISUAL_QUALITY.json"   --output "$OUT/PAPER_GRADE_STATUS.json"

cat <<EOF

Campaign v2            : $FROZEN/campaign-v2.json
Freeze provenance      : $FROZEN/campaign-v2-freeze.json
Hardware calibration   : $CAL/work-cost-model.json
Sparse-index scaling   : $SPARSE/sparse-discovery-summary.json
Campaign evidence      : $RESULTS/campaign-rows.jsonl
Wall timings           : $RESULTS/campaign-timings.jsonl
Evidence gates         : $RESULTS/campaign-gates.json
Held-out empirical     : $RESULTS/empirical-heldout.json
Answer                 : $RESULTS/REAL_CAMPAIGN_ANSWER.md
SIGGRAPH visuals       : $VIS
Visual-quality audit    : $VISUAL_QUALITY/CBRC_VISUAL_QUALITY.json
Paper-grade audit      : $OUT/PAPER_GRADE_STATUS.json

Scientific boundary:
  * hardware calibration is an isolated ms cost model, not a direct end-to-end speedup;
  * campaign-timings are measured phase wall times including orchestration overhead;
  * SfM global scale is canonicalized, not metrically measured;
  * all 60 frozen cases remain in evidence, including failures/fallbacks.
EOF

if (( CAMPAIGN_STATUS != 0 )); then
  echo "PAPER-GRADE V2 CAMPAIGN FAILED EVIDENCE GATES (exit $CAMPAIGN_STATUS)." >&2
  exit "$CAMPAIGN_STATUS"
fi
if (( REPORT_STATUS != 0 )); then
  echo "PAPER-GRADE V2 ANSWER REPORT FAILED (exit $REPORT_STATUS)." >&2
  exit "$REPORT_STATUS"
fi

echo
echo "PAPER-GRADE PUBLIC CBRC CAMPAIGN V2 PASSED."
