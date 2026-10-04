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

OUT="${MAVEB_TRAINED_3DGS_RESULTS_DIR:-$ROOT/build/trained-3dgs-campaign}"
SOURCE="$OUT/source"
WORLD_ROOT="$OUT/world"
FROZEN="$OUT/frozen-inputs"
RESULTS="$OUT/campaign"
VIS="$OUT/siggraph-visuals"
VISUAL_QUALITY="$OUT/visual-quality"

SEED="$BUILD_ROOT/tools/maveb-seed-trained-3dgs-world/maveb-seed-trained-3dgs-world"
REVISION="$BUILD_ROOT/tools/maveb-cbrc-revision/maveb-cbrc-revision"
ORACLE="$BUILD_ROOT/tools/maveb-cbrc-gaussian-oracle/maveb-cbrc-gaussian-oracle"

mkdir -p "$SOURCE" "$WORLD_ROOT" "$FROZEN" "$RESULTS" "$VIS" "$VISUAL_QUALITY"

echo "============================================================"
echo "MAVEB public trained-3DGS CBRC validation"
echo "============================================================"
echo "Repository : $ROOT"
echo "Git SHA    : $(git rev-parse HEAD)"
echo "Output     : $OUT"
echo "User data  : NONE"
echo

echo "==> [1/8] Ensuring Hugging Face download dependency"
if ! "$PYTHON" -c 'import huggingface_hub' >/dev/null 2>&1; then
  "$PYTHON" -m pip install "huggingface_hub>=0.34,<2"
fi

echo "==> [2/8] Fetching one public trained 3DGS model with frozen provenance"
FETCH_ARGS=(--output-dir "$SOURCE")
if [[ -n "${MAVEB_TRAINED_3DGS_REPO:-}" ]]; then
  FETCH_ARGS+=(--repo-id "$MAVEB_TRAINED_3DGS_REPO")
fi
if [[ -n "${MAVEB_TRAINED_3DGS_FILE:-}" ]]; then
  FETCH_ARGS+=(--file "$MAVEB_TRAINED_3DGS_FILE")
fi
"$PYTHON" benchmarks/scripts/cbrc_fetch_trained_3dgs.py "${FETCH_ARGS[@]}" > "$SOURCE/fetch.stdout"

echo "==> [3/8] Building trained-3DGS seeder and CBRC evidence tools"
cmake --preset "$BUILD_PRESET"
cmake --build --preset "$BUILD_PRESET" --target   maveb-seed-trained-3dgs-world   maveb-cbrc-revision   maveb-cbrc-gaussian-oracle   --parallel

echo "==> [4/8] Converting trained 3DGS into a persistent MAVEB world"
WORLD="$WORLD_ROOT/public-trained.aetherworld"
"$SEED"   --ply "$SOURCE/trained-point-cloud.ply"   --output "$WORLD"   --target-diagonal 2.0   --json   > "$WORLD_ROOT/trained-seed.json"

echo "==> [5/8] Freezing and running trained-3DGS revision cases"
rm -rf "$FROZEN" "$RESULTS"
mkdir -p "$FROZEN" "$RESULTS"
PREP_ARGS=(
  --archive "$WORLD"
  --output-dir "$FROZEN"
)
if [[ -f "$ROOT/build/public-real-v2/calibration/work-cost-model.json" ]]; then
  PREP_ARGS+=(--work-cost-model "$ROOT/build/public-real-v2/calibration/work-cost-model.json")
fi
"$PYTHON" benchmarks/scripts/cbrc_prepare_real_campaign.py "${PREP_ARGS[@]}"

set +e
export MAVEB_ORACLE_CACHE_DIR="${MAVEB_ORACLE_CACHE_DIR:-$RESULTS/.oracle-cache}"
"$PYTHON" benchmarks/scripts/cbrc_campaign.py   --campaign "$FROZEN/campaign.json"   --oracle "$ORACLE"   --revision-tool "$REVISION"   --git-sha "$(git rev-parse HEAD)"   --output-dir "$RESULTS"   --workers "$CASE_WORKERS"
CAMPAIGN_STATUS=$?
set -e

echo "==> [6/8] Generating trained-3DGS answer and visual package"
set +e
"$PYTHON" research/analysis/cbrc_real_campaign_report.py --results-dir "$RESULTS"
REPORT_STATUS=$?
set -e
"$PYTHON" research/visualization/cbrc_siggraph_visuals.py   --campaign-dir "$RESULTS"   --output-dir "$VIS"   --max-mosaic-cases 5

echo "==> [7/8] Measuring selected-repair visual fidelity against FULL-after"
"$PYTHON" research/analysis/cbrc_visual_quality.py \
  --campaign-dir "$RESULTS" \
  --output-dir "$VISUAL_QUALITY"

echo "==> [8/8] Freezing trained-3DGS validation status"
"$PYTHON" - "$OUT" "$CAMPAIGN_STATUS" "$REPORT_STATUS" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1])
campaign_status=int(sys.argv[2]); report_status=int(sys.argv[3])
gates=json.loads((root/"campaign/campaign-gates.json").read_text())
source=json.loads((root/"source/TRAINED_3DGS_SOURCE.json").read_text())
answer=json.loads((root/"campaign/REAL_CAMPAIGN_ANSWER.json").read_text())
status={
  "schemaVersion":1,
  "artifact":"maveb-trained-3dgs-validation-status",
  "pass": campaign_status==0 and report_status==0 and bool(gates.get("pass",False)),
  "source":source,
  "gates":gates,
  "answer":answer,
  "representation":"public trained 3DGS PLY with SH/opacity/scale/rotation preserved",
  "ownership":"deterministic spatial persistent entities, not semantic segmentation",
}
(root/"TRAINED_3DGS_STATUS.json").write_text(json.dumps(status,indent=2,sort_keys=True)+"\n")
print(json.dumps(status,indent=2,sort_keys=True))
PY

if (( CAMPAIGN_STATUS != 0 )); then
  echo "TRAINED-3DGS CAMPAIGN FAILED EVIDENCE GATES (exit $CAMPAIGN_STATUS)." >&2
  exit "$CAMPAIGN_STATUS"
fi
if (( REPORT_STATUS != 0 )); then
  echo "TRAINED-3DGS REPORT FAILED (exit $REPORT_STATUS)." >&2
  exit "$REPORT_STATUS"
fi

echo
echo "PUBLIC TRAINED-3DGS CBRC VALIDATION PASSED."
