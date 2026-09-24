#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

BUILD_PRESET="${MAVEB_RESEARCH_BUILD_PRESET:-research}"
BUILD_ROOT="$ROOT/build/$BUILD_PRESET"
CASE_WORKERS="${MAVEB_CASE_WORKERS:-4}"
export MAVEB_CASE_WORKERS="$CASE_WORKERS"
export MAVEB_ORACLE_BACKEND="${MAVEB_ORACLE_BACKEND:-cpu}"

PYTHON="${MAVEB_PYTHON:-$ROOT/.venv-maveb/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="${MAVEB_PYTHON:-python3}"
fi

OUT="${MAVEB_REAL_RESULTS_DIR:-$ROOT/build/research-real}"
PREP="$OUT/frozen-inputs"
CAMPAIGN="$PREP/campaign.json"
ORACLE="$BUILD_ROOT/tools/maveb-cbrc-gaussian-oracle/maveb-cbrc-gaussian-oracle"
REVISION="$BUILD_ROOT/tools/maveb-cbrc-revision/maveb-cbrc-revision"

mkdir -p "$OUT"

for tool in "$ORACLE" "$REVISION"; do
  if [[ ! -x "$tool" ]]; then
    echo "==> Building required native CBRC tools"
    cmake --preset "$BUILD_PRESET"
    cmake --build --preset "$BUILD_PRESET" --parallel
    break
  fi
done

echo "============================================================"
echo "MAVEB real CBRC campaign autopilot"
echo "============================================================"
echo "Repository : $ROOT"
echo "Git SHA    : $(git rev-parse HEAD)"
echo "Output     : $OUT"
echo

PREP_ARGS=(
  --output-dir "$PREP"
  --search-root "$ROOT"
  --search-root "$ROOT/build"
  --search-root "$HOME/Desktop"
  --search-root "$HOME/Documents"
  --search-root "$HOME/Downloads"
)

if [[ -n "${MAVEB_REAL_ARCHIVE:-}" ]]; then
  PREP_ARGS+=(--archive "$MAVEB_REAL_ARCHIVE")
fi

if [[ -n "${MAVEB_WORK_COST:-}" ]]; then
  [[ -f "$MAVEB_WORK_COST" ]] || {
    echo "MAVEB_WORK_COST does not exist: $MAVEB_WORK_COST" >&2
    exit 3
  }
  PREP_ARGS+=(--work-cost-model "$MAVEB_WORK_COST")
fi

echo "==> [1/4] Discovering and freezing real before-states"
"$PYTHON" benchmarks/scripts/cbrc_prepare_real_campaign.py "${PREP_ARGS[@]}"

echo "==> [2/4] Running independent real campaign"
set +e
export MAVEB_ORACLE_CACHE_DIR="${MAVEB_ORACLE_CACHE_DIR:-$OUT/campaign/.oracle-cache}"
"$PYTHON" benchmarks/scripts/cbrc_campaign.py   --campaign "$CAMPAIGN"   --oracle "$ORACLE"   --revision-tool "$REVISION"   --git-sha "$(git rev-parse HEAD)"   --output-dir "$OUT/campaign"   --workers "$CASE_WORKERS"
CAMPAIGN_STATUS=$?
set -e

echo "==> [3/4] Generating answer-first report"
set +e
"$PYTHON" research/analysis/cbrc_real_campaign_report.py   --results-dir "$OUT/campaign"
REPORT_STATUS=$?
set -e

echo "==> [4/4] Final evidence locations"
echo "Frozen campaign : $CAMPAIGN"
echo "Discovery       : $PREP/asset-discovery.json"
echo "Freeze hashes    : $PREP/campaign-freeze.json"
echo "Campaign gates   : $OUT/campaign/campaign-gates.json"
echo "Evaluation       : $OUT/campaign/campaign-evaluation.json"
echo "Baselines        : $OUT/campaign/baseline-summary.json"
echo "Paper artifacts  : $OUT/campaign/paper-artifacts"
echo "Answer report    : $OUT/campaign/REAL_CAMPAIGN_ANSWER.md"
echo

if (( CAMPAIGN_STATUS != 0 )); then
  echo "Real campaign did not clear all evidence gates (exit $CAMPAIGN_STATUS)." >&2
  exit "$CAMPAIGN_STATUS"
fi
if (( REPORT_STATUS != 0 )); then
  echo "Real campaign report marks the evidence gate as failed." >&2
  exit "$REPORT_STATUS"
fi

echo "REAL CAMPAIGN PASSED."
