#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

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

SEED="$ROOT/build/ci/tools/maveb-seed-trained-3dgs-world/maveb-seed-trained-3dgs-world"
REVISION="$ROOT/build/ci/tools/maveb-cbrc-revision/maveb-cbrc-revision"
ORACLE="$ROOT/build/ci/tools/maveb-cbrc-gaussian-oracle/maveb-cbrc-gaussian-oracle"

mkdir -p "$SOURCE" "$WORLD_ROOT" "$FROZEN" "$RESULTS" "$VIS"

echo "============================================================"
echo "MAVEB public trained-3DGS CBRC validation"
echo "============================================================"
echo "Repository : $ROOT"
echo "Git SHA    : $(git rev-parse HEAD)"
echo "Output     : $OUT"
echo "User data  : NONE"
echo

echo "==> [1/7] Ensuring Hugging Face download dependency"
if ! "$PYTHON" -c 'import huggingface_hub' >/dev/null 2>&1; then
  "$PYTHON" -m pip install "huggingface_hub>=0.34,<2"
fi

echo "==> [2/7] Fetching one public trained 3DGS model with frozen provenance"
FETCH_ARGS=(--output-dir "$SOURCE")
if [[ -n "${MAVEB_TRAINED_3DGS_REPO:-}" ]]; then
  FETCH_ARGS+=(--repo-id "$MAVEB_TRAINED_3DGS_REPO")
fi
if [[ -n "${MAVEB_TRAINED_3DGS_FILE:-}" ]]; then
  FETCH_ARGS+=(--file "$MAVEB_TRAINED_3DGS_FILE")
fi
"$PYTHON" benchmarks/scripts/cbrc_fetch_trained_3dgs.py "${FETCH_ARGS[@]}" > "$SOURCE/fetch.stdout"

echo "==> [3/7] Building trained-3DGS seeder and CBRC evidence tools"
cmake --preset ci
cmake --build --preset ci --target   maveb-seed-trained-3dgs-world   maveb-cbrc-revision   maveb-cbrc-gaussian-oracle   --parallel

echo "==> [4/7] Converting trained 3DGS into a persistent MAVEB world"
WORLD="$WORLD_ROOT/public-trained.aetherworld"
"$SEED"   --ply "$SOURCE/trained-point-cloud.ply"   --output "$WORLD"   --target-diagonal 2.0   --json   > "$WORLD_ROOT/trained-seed.json"

echo "==> [5/7] Freezing and running trained-3DGS revision cases"
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
"$PYTHON" benchmarks/scripts/cbrc_campaign.py   --campaign "$FROZEN/campaign.json"   --oracle "$ORACLE"   --revision-tool "$REVISION"   --git-sha "$(git rev-parse HEAD)"   --output-dir "$RESULTS"
CAMPAIGN_STATUS=$?
set -e

echo "==> [6/7] Generating trained-3DGS answer and visual package"
set +e
"$PYTHON" research/analysis/cbrc_real_campaign_report.py --results-dir "$RESULTS"
REPORT_STATUS=$?
set -e
"$PYTHON" research/visualization/cbrc_siggraph_visuals.py   --campaign-dir "$RESULTS"   --output-dir "$VIS"   --max-mosaic-cases 5
"$PYTHON" research/analysis/cbrc_visual_quality.py   --campaign-dir "$RESULTS"   --output-dir "$VISUAL_QUALITY"

echo "==> [7/7] Freezing trained-3DGS validation status"
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
