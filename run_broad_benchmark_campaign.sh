#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON="${MAVEB_PYTHON:-$ROOT/.venv-maveb/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="${MAVEB_PYTHON:-python3}"
fi

OUT="${MAVEB_BROAD_RESULTS_DIR:-$ROOT/build/broad-benchmark}"
IMPORT_DIR="$OUT/import"
WORLDS_DIR="$OUT/worlds"
CAL_DIR="$OUT/calibration"
FREEZE_DIR="$OUT/frozen"
RESULTS_DIR="$OUT/campaign"
VISUAL_DIR="$OUT/visual-quality"
STATS_DIR="$OUT/statistics"
CACHE_DIR="$OUT/.stage-cache"
WORLD_MANIFEST="$WORLD_MANIFEST"

REUSE="${MAVEB_BROAD_REUSE:-1}"
ADOPT_EXISTING="${MAVEB_BROAD_ADOPT_EXISTING:-0}"
ALLOW_PARTIAL="${MAVEB_BROAD_ALLOW_PARTIAL:-0}"
REUSE_PREPARED_WORLDS="${MAVEB_BROAD_REUSE_PREPARED_WORLDS:-0}"
PREPARED_WORLD_CANDIDATES="${MAVEB_BROAD_PREPARED_WORLD_CANDIDATES:-}"
MAX_IMAGES="${MAVEB_BROAD_MAX_IMAGES:-120}"
CASES_PER_SCENE="${MAVEB_BROAD_CASES_PER_SCENE:-15}"
BOOTSTRAP_ITERATIONS="${MAVEB_BROAD_BOOTSTRAP_ITERATIONS:-5000}"
SCENE_WORKERS="${MAVEB_BROAD_SCENE_WORKERS:-3}"
CASE_WORKERS="${MAVEB_BROAD_CASE_WORKERS:-4}"
export MAVEB_CASE_WORKERS="$CASE_WORKERS"
BUILD_PRESET="${MAVEB_BROAD_BUILD_PRESET:-research}"
BUILD_ROOT="$ROOT/build/$BUILD_PRESET"
export MAVEB_PROGRESS="${MAVEB_PROGRESS:-1}"
export MAVEB_ORACLE_CACHE_DIR="${MAVEB_ORACLE_CACHE_DIR:-$RESULTS_DIR/.oracle-cache}"
if [[ -z "${MAVEB_ORACLE_BACKEND:-}" ]]; then
  export MAVEB_ORACLE_BACKEND="cpu"
fi

DATASETS_CSV="${MAVEB_BROAD_DATASETS:-graphdeco-pretrained-3dgs,3rscan,scannetpp,arkitscenes,bonn-rgbd-dynamic}"
IFS=',' read -r -a DATASETS <<< "$DATASETS_CSV"
DATASET_ARGS=()
for dataset in "${DATASETS[@]}"; do
  [[ -n "$dataset" ]] || continue
  DATASET_ARGS+=(--dataset "$dataset")
done
if (( ${#DATASET_ARGS[@]} == 0 )); then
  echo "MAVEB_BROAD_DATASETS resolved to an empty dataset list." >&2
  exit 2
fi

mkdir -p "$IMPORT_DIR" "$WORLDS_DIR" "$CAL_DIR" "$FREEZE_DIR" "$RESULTS_DIR" "$VISUAL_DIR" "$STATS_DIR" "$CACHE_DIR"

ADOPTION_SENTINEL="$CACHE_DIR/adoption-complete"
if [[ "$ADOPT_EXISTING" == "1" && -f "$ADOPTION_SENTINEL" ]]; then
  echo "Existing-artifact adoption was already completed for this output; ignoring MAVEB_BROAD_ADOPT_EXISTING=1."
  ADOPT_EXISTING=0
fi

REVISION="$BUILD_ROOT/tools/maveb-cbrc-revision/maveb-cbrc-revision"
ORACLE="$BUILD_ROOT/tools/maveb-cbrc-gaussian-oracle/maveb-cbrc-gaussian-oracle"
WORK_BENCH="$BUILD_ROOT/tools/maveb-cbrc-work-bench/maveb-cbrc-work-bench"
TRAINED_SEED="$BUILD_ROOT/tools/maveb-seed-trained-3dgs-world/maveb-seed-trained-3dgs-world"
NATIVE_SEED="$BUILD_ROOT/tools/maveb-seed-world/maveb-seed-world"
CACHE_KEY="$ROOT/benchmarks/scripts/cbrc_cache_key.py"
STORAGE_DOCTOR="$ROOT/benchmarks/scripts/cbrc_storage_doctor.py"
export MAVEB_REQUIRE_COW="${MAVEB_REQUIRE_COW:-1}"
MIN_FREE_GIB="${MAVEB_MIN_FREE_GIB:-5}"

COLMAP_BIN="${MAVEB_COLMAP:-}"
if [[ -z "$COLMAP_BIN" ]]; then
  for candidate in     "$ROOT/.aether-deps/colmap-install/bin/colmap"     "$ROOT/.aether-deps/bin/colmap"; do
    if [[ -x "$candidate" ]]; then
      COLMAP_BIN="$candidate"
      break
    fi
  done
fi
if [[ -z "$COLMAP_BIN" ]] && command -v colmap >/dev/null 2>&1; then
  COLMAP_BIN="$(command -v colmap)"
fi

FFMPEG_BIN="${MAVEB_FFMPEG:-}"
if [[ -z "$FFMPEG_BIN" ]] && command -v ffmpeg >/dev/null 2>&1; then
  FFMPEG_BIN="$(command -v ffmpeg)"
fi

HEAD_SHA="$(git rev-parse HEAD)"

step() {
  local number="$1"
  shift
  echo
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "▶ [$number/9] $*"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

cache_hit() {
  local name="$1"
  local key="$2"
  local done_file="$CACHE_DIR/$name.done"
  [[ "$REUSE" == "1" && -f "$done_file" && "$(cat "$done_file")" == "$key" ]]
}

cache_complete() {
  local name="$1"
  local key="$2"
  printf '%s\n' "$key" > "$CACHE_DIR/$name.done"
  rm -f "$CACHE_DIR/$name.inprogress"
}

cache_begin() {
  local name="$1"
  local key="$2"
  printf '%s\n' "$key" > "$CACHE_DIR/$name.inprogress"
}

same_inprogress() {
  local name="$1"
  local key="$2"
  [[ -f "$CACHE_DIR/$name.inprogress" && "$(cat "$CACHE_DIR/$name.inprogress")" == "$key" ]]
}

cache_banner() {
  local message="$1"
  echo "  [██████████████████████████████] 100.00% | CACHE | $message"
}

validate_calibration() {
  "$PYTHON" - "$CAL_DIR/work-cost-model.json" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1])
if not p.is_file():
    raise SystemExit(1)
m=json.loads(p.read_text())
if not isinstance(m,dict) or not m:
    raise SystemExit(1)
print(f"  ✓ validated existing hardware work calibration: {p}")
PY
}

validate_worlds() {
  "$PYTHON" - "$WORLD_MANIFEST" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1])
if not p.is_file():
    raise SystemExit(1)
m=json.loads(p.read_text())
if m.get("failedWorlds",1) or m.get("blockedWorlds",1) or m.get("readyWorlds",0)<2:
    raise SystemExit(1)
for r in m.get("records",[]):
    if r.get("status")=="ready":
        w=r.get("world")
        if not w or not Path(w).is_file():
            raise SystemExit(1)
print(f"  ✓ validated {m['readyWorlds']} prepared worlds "
      f"({m.get('nativePreparedWorlds',0)} native, {m.get('rgbFallbackWorlds',0)} RGB fallback)")
PY
}

validate_freeze() {
  "$PYTHON" - "$FREEZE_DIR/broad-campaign.json" "$FREEZE_DIR/BROAD_CAMPAIGN_FREEZE.json" <<'PY'
import json,sys
from pathlib import Path
campaign=Path(sys.argv[1]); freeze=Path(sys.argv[2])
if not campaign.is_file() or not freeze.is_file():
    raise SystemExit(1)
c=json.loads(campaign.read_text())
if not c.get("cases"):
    raise SystemExit(1)
regimes=sorted({str(x.get("coupling_regime","")).lower() for x in c["cases"]})
expected_high=bool(set(regimes)&{"high","adversarial"})
expected_policy={
    "fullFallback":"observed-outcome-not-required",
    "highCouplingRequired":expected_high,
    "frozenCouplingRegimes":regimes,
}
if c.get("require_full_fallback") is not False:
    raise SystemExit(1)
if bool(c.get("require_high_coupling")) != expected_high:
    raise SystemExit(1)
if c.get("broad_gate_policy") != expected_policy:
    raise SystemExit(1)
print(f"  ✓ validated frozen campaign: {len(c['cases'])} cases; gate policy current")
PY
}

validate_step6() {
  "$PYTHON" - "$FREEZE_DIR/broad-campaign.json" "$RESULTS_DIR" <<'PY'
import json,sys
from pathlib import Path
campaign=json.loads(Path(sys.argv[1]).read_text())
root=Path(sys.argv[2])
required=[
    root/"campaign-rows.jsonl",
    root/"campaign-baselines.jsonl",
    root/"campaign-gates.json",
    root/"campaign-evaluation.json",
    root/"planner-parity.json",
    root/"campaign-execution.json",
]
if not all(p.is_file() for p in required):
    raise SystemExit(1)
rows=[x for x in (root/"campaign-rows.jsonl").read_text().splitlines() if x.strip()]
if len(rows) != len(campaign["cases"]):
    raise SystemExit(1)
gates=json.loads((root/"campaign-gates.json").read_text())
if not gates.get("pass",False):
    raise SystemExit(1)
parity=json.loads((root/"planner-parity.json").read_text())
if len(parity) != len(campaign["cases"]) or not all(x.get("pass",False) for x in parity):
    raise SystemExit(1)
print(f"  ✓ validated Step 6: {len(rows)}/{len(campaign['cases'])} cases, gates PASS")
PY
}

echo "============================================================"
echo "MAVEB CBRC broad cross-dataset campaign"
echo "============================================================"
echo "Repository       : $ROOT"
echo "Runner Git SHA   : $HEAD_SHA"
echo "Output           : $OUT"
echo "Stage cache      : $CACHE_DIR"
echo "Datasets         : $DATASETS_CSV"
echo "Reuse            : $REUSE"
echo "Adopt existing   : $ADOPT_EXISTING"
echo "Allow partial    : $ALLOW_PARTIAL"
echo "Reuse old worlds : $REUSE_PREPARED_WORLDS"
echo "Cases / scene    : $CASES_PER_SCENE"
echo "Bootstrap iters  : $BOOTSTRAP_ITERATIONS"
echo "Scene workers    : $SCENE_WORKERS"
echo "Case workers     : $CASE_WORKERS"
echo "Build preset     : $BUILD_PRESET"
echo "Oracle backend   : $MAVEB_ORACLE_BACKEND"
echo "Oracle cache     : $MAVEB_ORACLE_CACHE_DIR"
echo "Require COW      : $MAVEB_REQUIRE_COW"
echo "Min free disk    : $MIN_FREE_GIB GiB"
echo
"$PYTHON" "$STORAGE_DOCTOR" --repo "$ROOT" --minimum-free-gib 0 || true
echo

step 1 "Validating/importing selected datasets"
RAW_IMPORT="$IMPORT_DIR/BROAD_IMPORT.json"
EFFECTIVE_IMPORT="$IMPORT_DIR/BROAD_IMPORT_EFFECTIVE.json"
if "$PYTHON" benchmarks/scripts/cbrc_broad_benchmark.py import \
    --output "$RAW_IMPORT" "${DATASET_ARGS[@]}"; then
  IMPORT_STATUS=0
else
  IMPORT_STATUS=$?
fi
if (( IMPORT_STATUS != 0 && IMPORT_STATUS != 2 )); then
  echo "Dataset import failed unexpectedly with exit code $IMPORT_STATUS." >&2
  exit "$IMPORT_STATUS"
fi

ACTIVE_IMPORT="$RAW_IMPORT"
SELECT_IMPORT="$ROOT/benchmarks/scripts/cbrc_select_import.py"
SELECT_ARGS=(--input "$RAW_IMPORT" --output "$EFFECTIVE_IMPORT")
if [[ "$ALLOW_PARTIAL" == "1" ]]; then
  SELECT_ARGS+=(--allow-partial)
fi

SELECT_STATUS=0
if EFFECTIVE_DATASETS="$("$PYTHON" "$SELECT_IMPORT" "${SELECT_ARGS[@]}")"; then
  if [[ "$ALLOW_PARTIAL" == "1" ]]; then
    ACTIVE_IMPORT="$EFFECTIVE_IMPORT"
  fi
else
  SELECT_STATUS=$?
fi

REUSED_PREPARED_WORLDS=0
if (( SELECT_STATUS != 0 )); then
  if [[ "$ALLOW_PARTIAL" == "1" && "$REUSE_PREPARED_WORLDS" == "1" ]]; then
    WORLD_SELECTOR="$ROOT/benchmarks/scripts/cbrc_select_prepared_worlds.py"
    WORLD_ARGS=()
    IFS=':' read -r -a WORLD_CANDIDATES <<< "$PREPARED_WORLD_CANDIDATES"
    for candidate in "${WORLD_CANDIDATES[@]}"; do
      [[ -n "$candidate" ]] || continue
      WORLD_ARGS+=(--candidate "$candidate")
    done
    if (( ${#WORLD_ARGS[@]} == 0 )); then
      echo "Prepared-world reuse was enabled but no candidate manifests were configured." >&2
      exit "$SELECT_STATUS"
    fi
    if EFFECTIVE_DATASETS="$("$PYTHON" "$WORLD_SELECTOR" "${WORLD_ARGS[@]}" --output "$WORLD_MANIFEST")"; then
      REUSED_PREPARED_WORLDS=1
      echo "  ↳ raw dataset roots unavailable; using development-only prepared-world reuse"
    else
      exit "$SELECT_STATUS"
    fi
  else
    exit "$SELECT_STATUS"
  fi
fi

DATASETS_CSV="$EFFECTIVE_DATASETS"
IFS=',' read -r -a DATASETS <<< "$DATASETS_CSV"
DATASET_ARGS=()
for dataset in "${DATASETS[@]}"; do
  [[ -n "$dataset" ]] || continue
  DATASET_ARGS+=(--dataset "$dataset")
done
echo "Effective datasets : $DATASETS_CSV"

step 2 "Building CBRC research tools"
cmake --preset "$BUILD_PRESET"
cmake --build --preset "$BUILD_PRESET"   --target     maveb-cbrc-revision     maveb-cbrc-gaussian-oracle     maveb-cbrc-work-bench     maveb-seed-trained-3dgs-world     maveb-seed-world   --parallel

STEP3_KEY_ARGS=(
  --label step3-world-preparation-v2
  --file "$ACTIVE_IMPORT"
  --file "$ROOT/benchmarks/scripts/cbrc_prepare_broad_worlds.py"
  --file "$ROOT/benchmarks/scripts/cbrc_native_proxy.py"
  --file "$ROOT/benchmarks/scripts/cbrc_seed_colmap_world.py"
  --file "$TRAINED_SEED"
  --file "$NATIVE_SEED"
  --value "datasets=$DATASETS_CSV"
  --value "max_images=$MAX_IMAGES"
)
PREP_TOOL_ARGS=()
if [[ -n "$COLMAP_BIN" && -x "$COLMAP_BIN" ]]; then
  STEP3_KEY_ARGS+=(--file "$COLMAP_BIN")
  PREP_TOOL_ARGS+=(--colmap "$COLMAP_BIN")
fi
if [[ -n "$FFMPEG_BIN" && -x "$FFMPEG_BIN" ]]; then
  STEP3_KEY_ARGS+=(--file "$FFMPEG_BIN")
  PREP_TOOL_ARGS+=(--ffmpeg "$FFMPEG_BIN")
fi
STEP3_KEY="$("$PYTHON" "$CACHE_KEY" "${STEP3_KEY_ARGS[@]}")"

step 3 "Preparing normalized persistent worlds"
if [[ "$REUSED_PREPARED_WORLDS" == "1" ]]; then
  validate_worlds
  cache_complete step3 "$STEP3_KEY"
  cache_banner "Step 3 reused — development campaign adopted existing prepared worlds"
elif [[ "${MAVEB_BROAD_FORCE_STEP3:-0}" != "1" ]] && cache_hit step3 "$STEP3_KEY" && validate_worlds; then
  cache_banner "Step 3 reused — normalized worlds already match inputs/toolchain"
elif [[ "${MAVEB_BROAD_FORCE_STEP3:-0}" != "1" && "$ADOPT_EXISTING" == "1" ]] && validate_worlds >/dev/null 2>&1; then
  validate_worlds
  cache_complete step3 "$STEP3_KEY"
  cache_banner "Step 3 adopted existing validated worlds"
else
  if [[ "$REUSE" != "1" || "${MAVEB_BROAD_FORCE_STEP3:-0}" == "1" ]] || ! same_inprogress step3 "$STEP3_KEY"; then
    rm -rf "$WORLDS_DIR"
    mkdir -p "$WORLDS_DIR"
  else
    echo "  ↻ matching interrupted Step-3 checkpoint found; resuming prepared scenes"
  fi
  cache_begin step3 "$STEP3_KEY"
  "$PYTHON" benchmarks/scripts/cbrc_prepare_broad_worlds.py     --import-manifest "$ACTIVE_IMPORT"     --output-dir "$WORLDS_DIR"     --trained-seeder "$TRAINED_SEED"     --native-seeder "$NATIVE_SEED"     "${PREP_TOOL_ARGS[@]}"     "${DATASET_ARGS[@]}"     --max-images "$MAX_IMAGES"     --workers "$SCENE_WORKERS"     --resume     --summary-only
  validate_worlds
  cache_complete step3 "$STEP3_KEY"
fi

echo
echo "Checking disk budget before freeze/execution..."
if ! "$PYTHON" "$STORAGE_DOCTOR" \
    --repo "$ROOT" \
    --minimum-free-gib "$MIN_FREE_GIB"; then
  echo
  echo "Insufficient free disk for a safe campaign run." >&2
  echo "Run this safe cleanup, then rerun the campaign:" >&2
  echo "  \"$PYTHON\" \"$STORAGE_DOCTOR\" --repo \"$ROOT\" --cleanup-safe --minimum-free-gib 0" >&2
  exit 3
fi

STEP4_KEY="$("$PYTHON" "$CACHE_KEY"   --label step4-work-calibration-v1   --file "$WORK_BENCH"   --file "$ROOT/benchmarks/scripts/cbrc_calibrate_work.py"   --value "arch=$(uname -m)"   --value "os=$(uname -s)"   --value "gaussians=${MAVEB_CAL_GAUSSIANS:-1000000}"   --value "publication_bytes=${MAVEB_CAL_PUBLICATION_BYTES:-268435456}"   --value "pixels=${MAVEB_CAL_PIXELS:-921600}"   --value "repeats=${MAVEB_CAL_REPEATS:-9}")"

step 4 "Freezing one hardware work calibration"
if [[ "${MAVEB_BROAD_FORCE_STEP4:-0}" != "1" ]] && cache_hit step4 "$STEP4_KEY" && validate_calibration; then
  cache_banner "Step 4 reused — hardware work calibration unchanged"
elif [[ "${MAVEB_BROAD_FORCE_STEP4:-0}" != "1" && "$ADOPT_EXISTING" == "1" ]] && validate_calibration >/dev/null 2>&1; then
  validate_calibration
  cache_complete step4 "$STEP4_KEY"
  cache_banner "Step 4 adopted existing hardware calibration"
else
  rm -rf "$CAL_DIR"
  mkdir -p "$CAL_DIR"
  CAL_ID="broad-$(uname -m)-${STEP4_KEY:0:12}"
  "$WORK_BENCH"     --gaussians "${MAVEB_CAL_GAUSSIANS:-1000000}"     --publication-bytes "${MAVEB_CAL_PUBLICATION_BYTES:-268435456}"     --pixels "${MAVEB_CAL_PIXELS:-921600}"     --repeats "${MAVEB_CAL_REPEATS:-9}"     --calibration-id "$CAL_ID"     > "$CAL_DIR/calibration-rows.jsonl"
  "$PYTHON" benchmarks/scripts/cbrc_calibrate_work.py     --input "$CAL_DIR/calibration-rows.jsonl"     --version "$CAL_ID"     --minimum-repeats 5     --output "$CAL_DIR/work-cost-model.json"     > "$CAL_DIR/work-cost-model.stdout.json"
  cache_complete step4 "$STEP4_KEY"
fi

STEP5_KEY="$("$PYTHON" "$CACHE_KEY"   --label step5-broad-freeze-v3-lazy-inputs   --file "$WORLD_MANIFEST"   --file "$CAL_DIR/work-cost-model.json"   --file "$ROOT/benchmarks/scripts/cbrc_freeze_broad_campaign.py"   --file "$ROOT/benchmarks/scripts/cbrc_prepare_campaign_v2.py"   --file "$ROOT/benchmarks/scripts/cbrc_prepare_real_campaign.py"   --file "$ROOT/benchmarks/scripts/cbrc_migrate_broad_gate_policy.py"   --file "$ROOT/benchmarks/scripts/cbrc_storage.py"   --value "datasets=$DATASETS_CSV"   --value "cases_per_scene=$CASES_PER_SCENE")"

step 5 "Freezing cross-dataset cases before reading outcomes"
if [[ "$ADOPT_EXISTING" == "1" && -f "$FREEZE_DIR/broad-campaign.json" && -f "$FREEZE_DIR/BROAD_CAMPAIGN_FREEZE.json" ]]; then
  "$PYTHON" benchmarks/scripts/cbrc_migrate_broad_gate_policy.py \
    --campaign "$FREEZE_DIR/broad-campaign.json" \
    --freeze "$FREEZE_DIR/BROAD_CAMPAIGN_FREEZE.json" \
    --runner-git-sha "$HEAD_SHA"
fi
if [[ "${MAVEB_BROAD_FORCE_STEP5:-0}" != "1" ]] && cache_hit step5 "$STEP5_KEY" && validate_freeze; then
  cache_banner "Step 5 reused — frozen case matrix unchanged"
elif [[ "${MAVEB_BROAD_FORCE_STEP5:-0}" != "1" && "$ADOPT_EXISTING" == "1" ]] && validate_freeze >/dev/null 2>&1; then
  validate_freeze
  cache_complete step5 "$STEP5_KEY"
  cache_banner "Step 5 adopted existing frozen campaign"
else
  rm -rf "$FREEZE_DIR"
  mkdir -p "$FREEZE_DIR"
  "$PYTHON" benchmarks/scripts/cbrc_freeze_broad_campaign.py     --worlds "$WORLD_MANIFEST"     --output-dir "$FREEZE_DIR"     --cases-per-scene "$CASES_PER_SCENE"     --work-cost-model "$CAL_DIR/work-cost-model.json"     "${DATASET_ARGS[@]}"
  validate_freeze
  cache_complete step5 "$STEP5_KEY"
fi

STEP6_CASE_KEY="$("$PYTHON" "$CACHE_KEY"   --label step6-case-computation-v3-compacted   --file "$FREEZE_DIR/broad-campaign.json"   --file "$FREEZE_DIR/BROAD_CAMPAIGN_FREEZE.json"   --file "$ORACLE"   --file "$REVISION"   --file "$ROOT/benchmarks/scripts/cbrc_evidence_bundle.py"   --file "$ROOT/benchmarks/scripts/cbrc_bind_live_revision.py"   --file "$ROOT/benchmarks/scripts/cbrc_replay.py"   --file "$ROOT/benchmarks/scripts/cbrc_evaluate.py"   --file "$ROOT/research/experiments/cbrc_baseline_suite.py"   --file "$ROOT/research/cbrc/core.py"   --file "$ROOT/research/cbrc/edges.py"   --file "$ROOT/benchmarks/scripts/cbrc_campaign.py"   --file "$ROOT/benchmarks/scripts/cbrc_storage.py"   --value "require_cow=$MAVEB_REQUIRE_COW"   --value "oracle_backend=$MAVEB_ORACLE_BACKEND")"

CASE_KEY_FILE="$CACHE_DIR/step6.case-key"
EVIDENCE_SHA_FILE="$CACHE_DIR/step6.evidence-sha"

if [[ "$REUSE" != "1" || "${MAVEB_BROAD_FORCE_STEP6:-0}" == "1" ]]; then
  rm -rf "$RESULTS_DIR"
  mkdir -p "$RESULTS_DIR"
  rm -f "$CASE_KEY_FILE" "$EVIDENCE_SHA_FILE" "$CACHE_DIR/step6.done"
fi

if [[ -f "$CASE_KEY_FILE" && "$(cat "$CASE_KEY_FILE")" == "$STEP6_CASE_KEY" && -f "$EVIDENCE_SHA_FILE" ]]; then
  EVIDENCE_SHA="$(cat "$EVIDENCE_SHA_FILE")"
else
  if [[ "$ADOPT_EXISTING" == "1" && -d "$RESULTS_DIR/cases" ]]; then
    EVIDENCE_SHA="$("$PYTHON" - "$RESULTS_DIR" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1])
for p in sorted(root.glob("cases/*/replay-manifest.json")):
    try:
        value=str(json.loads(p.read_text()).get("git_sha","")).strip()
    except Exception:
        continue
    if value:
        print(value)
        raise SystemExit(0)
raise SystemExit(1)
PY
)" || EVIDENCE_SHA="$HEAD_SHA"
    echo "  ↻ adopting existing Step-6 evidence SHA: $EVIDENCE_SHA"
  else
    rm -rf "$RESULTS_DIR"
    mkdir -p "$RESULTS_DIR"
    EVIDENCE_SHA="$HEAD_SHA"
  fi
  printf '%s\n' "$STEP6_CASE_KEY" > "$CASE_KEY_FILE"
  printf '%s\n' "$EVIDENCE_SHA" > "$EVIDENCE_SHA_FILE"
  rm -f "$CACHE_DIR/step6.done"
fi

STEP6_FINAL_KEY="$("$PYTHON" "$CACHE_KEY"   --label step6-finalization-v2   --file "$ROOT/benchmarks/scripts/cbrc_campaign.py"   --file "$ROOT/research/analysis/cbrc_paper_artifacts.py"   --value "case_key=$STEP6_CASE_KEY"   --value "evidence_git_sha=$EVIDENCE_SHA")"

step 6 "Executing CBRC + oracle + baselines + ablations"
if [[ "${MAVEB_BROAD_FORCE_STEP6:-0}" != "1" ]] && cache_hit step6 "$STEP6_FINAL_KEY" && validate_step6; then
  cache_banner "Step 6 reused — all cases/oracle/baselines/ablations already complete"
else
  if [[ "$ADOPT_EXISTING" == "1" ]]; then
    "$PYTHON" benchmarks/scripts/cbrc_campaign.py \
      --campaign "$FREEZE_DIR/broad-campaign.json" \
      --freeze-provenance "$FREEZE_DIR/BROAD_CAMPAIGN_FREEZE.json" \
      --oracle "$ORACLE" \
      --revision-tool "$REVISION" \
      --git-sha "$EVIDENCE_SHA" \
      --output-dir "$RESULTS_DIR" \
      --workers "$CASE_WORKERS" \
      --resume \
      --adopt-existing
  else
    "$PYTHON" benchmarks/scripts/cbrc_campaign.py \
      --campaign "$FREEZE_DIR/broad-campaign.json" \
      --freeze-provenance "$FREEZE_DIR/BROAD_CAMPAIGN_FREEZE.json" \
      --oracle "$ORACLE" \
      --revision-tool "$REVISION" \
      --git-sha "$EVIDENCE_SHA" \
      --output-dir "$RESULTS_DIR" \
      --workers "$CASE_WORKERS" \
      --resume
  fi
  validate_step6
  cache_complete step6 "$STEP6_FINAL_KEY"
fi

STEP7_KEY="$("$PYTHON" "$CACHE_KEY"   --label step7-visual-quality-v1   --file "$RESULTS_DIR/campaign-rows.jsonl"   --file "$ROOT/research/analysis/cbrc_visual_quality.py"   --value "step6=$STEP6_FINAL_KEY")"

step 7 "Measuring selected-render fidelity against FULL-after"
if [[ "${MAVEB_BROAD_FORCE_STEP7:-0}" != "1" ]] && cache_hit step7 "$STEP7_KEY" && [[ -f "$VISUAL_DIR/CBRC_VISUAL_QUALITY.json" ]]; then
  cache_banner "Step 7 reused — visual-fidelity report unchanged"
else
  rm -rf "$VISUAL_DIR"
  mkdir -p "$VISUAL_DIR"
  "$PYTHON" research/analysis/cbrc_visual_quality.py     --campaign-dir "$RESULTS_DIR"     --output-dir "$VISUAL_DIR"
  cache_complete step7 "$STEP7_KEY"
fi

STEP8_KEY="$("$PYTHON" "$CACHE_KEY"   --label step8-cross-dataset-statistics-v1   --file "$RESULTS_DIR/campaign-rows.jsonl"   --file "$RESULTS_DIR/campaign-baselines.jsonl"   --file "$ROOT/research/analysis/cbrc_cross_dataset_statistics.py"   --value "bootstrap_iterations=$BOOTSTRAP_ITERATIONS")"

step 8 "Computing cross-dataset statistics"
if [[ "${MAVEB_BROAD_FORCE_STEP8:-0}" != "1" ]] && cache_hit step8 "$STEP8_KEY" && [[ -f "$STATS_DIR/CROSS_DATASET_STATISTICS.json" ]]; then
  cache_banner "Step 8 reused — statistics unchanged"
else
  rm -rf "$STATS_DIR"
  mkdir -p "$STATS_DIR"
  "$PYTHON" research/analysis/cbrc_cross_dataset_statistics.py     --rows "$RESULTS_DIR/campaign-rows.jsonl"     --baselines "$RESULTS_DIR/campaign-baselines.jsonl"     --output-dir "$STATS_DIR"     --bootstrap-iterations "$BOOTSTRAP_ITERATIONS"
  cache_complete step8 "$STEP8_KEY"
fi

step 9 "Writing campaign completion manifest"
"$PYTHON" - "$OUT" "$DATASETS_CSV" "$EVIDENCE_SHA" "$HEAD_SHA" <<'PY'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve()
datasets=sys.argv[2].split(",")
evidence_git_sha=sys.argv[3]
runner_git_sha=sys.argv[4]
files=[
    root/"import/BROAD_IMPORT.json",
    root/"worlds/BROAD_WORLDS.json",
    root/"calibration/work-cost-model.json",
    root/"frozen/broad-campaign.json",
    root/"frozen/BROAD_CAMPAIGN_FREEZE.json",
    root/"campaign/campaign-rows.jsonl",
    root/"campaign/campaign-gates.json",
    root/"campaign/campaign-evaluation.json",
    root/"campaign/campaign-baselines.jsonl",
    root/"campaign/planner-parity.json",
    root/"campaign/campaign-execution.json",
    root/"visual-quality/CBRC_VISUAL_QUALITY.json",
    root/"statistics/CROSS_DATASET_STATISTICS.json",
]
def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()
missing=[str(p) for p in files if not p.is_file()]
if missing:
    raise SystemExit("missing final evidence:\n" + "\n".join(missing))
manifest={
  "schemaVersion":2,
  "artifact":"maveb-cbrc-broad-campaign-completion",
  "gitSha":evidence_git_sha,
  "evidenceGitSha":evidence_git_sha,
  "runnerGitSha":runner_git_sha,
  "datasets":datasets,
  "files":[
      {"path":str(p.relative_to(root)),"sha256":sha(p),"bytes":p.stat().st_size}
      for p in files
  ],
}
(root/"BROAD_CAMPAIGN_COMPLETE.json").write_text(
    json.dumps(manifest,indent=2,sort_keys=True)+"\n"
)
print(json.dumps({
    "artifact":manifest["artifact"],
    "evidenceGitSha":evidence_git_sha,
    "runnerGitSha":runner_git_sha,
    "datasets":datasets,
    "files":len(files),
    "completionManifest":str(root/"BROAD_CAMPAIGN_COMPLETE.json"),
},indent=2,sort_keys=True))
PY

if [[ "$ADOPT_EXISTING" == "1" ]]; then
  : > "$ADOPTION_SENTINEL"
fi

cat <<EOF

BROAD MAVEB CAMPAIGN COMPLETE

Import manifest    : $IMPORT_DIR/BROAD_IMPORT.json
Prepared worlds    : $WORLD_MANIFEST
Frozen campaign    : $FREEZE_DIR/broad-campaign.json
Campaign rows      : $RESULTS_DIR/campaign-rows.jsonl
Visual fidelity    : $VISUAL_DIR/CBRC_VISUAL_QUALITY.json
Statistics         : $STATS_DIR/CROSS_DATASET_STATISTICS.json
Completion manifest: $OUT/BROAD_CAMPAIGN_COMPLETE.json
Stage cache        : $CACHE_DIR
Evidence Git SHA   : $EVIDENCE_SHA
Runner Git SHA     : $HEAD_SHA

Reuse controls:
  MAVEB_BROAD_REUSE=1            reuse matching completed stages (default)
  MAVEB_BROAD_FORCE_STEP3=1      rebuild normalized worlds
  MAVEB_BROAD_FORCE_STEP4=1      rerun hardware calibration
  MAVEB_BROAD_FORCE_STEP5=1      regenerate frozen cases
  MAVEB_BROAD_FORCE_STEP6=1      discard/recompute all Step-6 cases
  MAVEB_BROAD_FORCE_STEP7=1      rerun visual fidelity
  MAVEB_BROAD_FORCE_STEP8=1      rerun statistics
  MAVEB_BROAD_ADOPT_EXISTING=1   one-time migration of validated pre-cache artifacts
  MAVEB_BROAD_ALLOW_PARTIAL=1    development only: run ready scenes and skip unavailable datasets
  MAVEB_BROAD_SCENE_WORKERS=3     concurrent world-preparation scenes
  MAVEB_BROAD_CASE_WORKERS=4      concurrent independent CBRC cases
  MAVEB_ORACLE_CPU_THREADS=N       optional per-oracle CPU thread override
  MAVEB_BROAD_BUILD_PRESET=research optimized Release research binaries
  MAVEB_ORACLE_BACKEND=cpu       publication default; set auto/metal after GPU parity validation
  MAVEB_ORACLE_CACHE_DIR=...      shared immutable render cache for Step-6 workers

Scientific boundary:
  * cache hits require deterministic fingerprints of the relevant inputs, tools, scripts, and parameters;
  * incomplete Step-3 worlds and Step-6 cases resume only under matching fingerprints;
  * broad/reviewer case inputs are lazily materialized only when executed;
  * macOS materialization uses APFS copy-on-write and refuses silent full copies by default;
  * completed cases compact mutable world/sidecar files after evidence is captured;
  * an incomplete Step-6 case is restored from its immutable source before retry;
  * evidence keeps the Git SHA that actually generated/replayed it, even if a later runner only reuses it;
  * no dataset-specific threshold or result is changed by caching.
EOF
