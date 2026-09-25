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

if [[ -n "${MAVEB_REVIEWER_SOURCE_ROOT:-}" ]]; then
  SOURCE_ROOT="$MAVEB_REVIEWER_SOURCE_ROOT"
elif [[ -f "$ROOT/build/broad-benchmark-paper/worlds/BROAD_WORLDS.json" ]]; then
  SOURCE_ROOT="$ROOT/build/broad-benchmark-paper"
else
  SOURCE_ROOT="$ROOT/build/broad-benchmark-smoke"
fi
OUT="${MAVEB_V6_RESULTS_DIR:-$ROOT/build/reviewer-certificate-v6-breadth}"
SCENES_PER_DATASET="5"
REUSE="${MAVEB_REVIEWER_REUSE:-1}"
ANALYSIS_ONLY="${MAVEB_REVIEWER_ANALYSIS_ONLY:-0}"

WORLDS="$SOURCE_ROOT/worlds/BROAD_WORLDS.json"
CALIBRATION="$SOURCE_ROOT/calibration/work-cost-model.json"
IMPORT="$SOURCE_ROOT/import/BROAD_IMPORT.json"
FREEZE="$OUT/frozen"
CAMPAIGN="$OUT/campaign"
ANALYSIS="$OUT/analysis"
VISUALS="$OUT/visuals"
CACHE="$OUT/.stage-cache"

REVISION="$BUILD_ROOT/tools/maveb-cbrc-revision/maveb-cbrc-revision"
ORACLE="$BUILD_ROOT/tools/maveb-cbrc-gaussian-oracle/maveb-cbrc-gaussian-oracle"
CACHE_KEY="$ROOT/benchmarks/scripts/cbrc_cache_key.py"
STORAGE_DOCTOR="$ROOT/benchmarks/scripts/cbrc_storage_doctor.py"
CASE_COMPACTOR="$ROOT/benchmarks/scripts/cbrc_compact_completed_cases.py"
VISUAL_REGEN="$ROOT/research/analysis/cbrc_regenerate_reviewer_visual_cases.py"
export MAVEB_REQUIRE_COW="${MAVEB_REQUIRE_COW:-1}"
MIN_FREE_GIB="${MAVEB_MIN_FREE_GIB:-20}"

mkdir -p "$FREEZE" "$CAMPAIGN" "$ANALYSIS" "$VISUALS" "$CACHE"

for required in "$WORLDS" "$CALIBRATION" "$IMPORT"; do
  if [[ ! -f "$required" ]]; then
    echo "Missing prerequisite: $required" >&2
    echo "Complete/adopt the broad smoke campaign first." >&2
    exit 2
  fi
done

HEAD_SHA="$(git rev-parse HEAD)"
EXECUTION_GIT_SHA="$HEAD_SHA"
RESUME_STATE="$CAMPAIGN/CAMPAIGN_RESUME_STATE.json"
if [[ "$REUSE" == "1" && -f "$RESUME_STATE" ]]; then
  PRIOR_GIT_SHA="$("$PYTHON" - "$RESUME_STATE" <<'PY'
import json,sys
from pathlib import Path
payload=json.loads(Path(sys.argv[1]).read_text())
print(str(payload.get("gitSha","")).strip())
PY
)"
  if [[ -n "$PRIOR_GIT_SHA" ]]; then
    EXECUTION_GIT_SHA="$PRIOR_GIT_SHA"
  fi
fi

step() {
  echo
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "▶ [$1/5] $2"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

cache_hit() {
  local name="$1"
  local key="$2"
  [[ "$REUSE" == "1" && -f "$CACHE/$name.done" && "$(cat "$CACHE/$name.done")" == "$key" ]]
}

cache_done() {
  printf '%s\n' "$2" > "$CACHE/$1.done"
}

echo "============================================================"
echo "MAVEB v6 confirmatory breadth campaign"
echo "============================================================"
echo "Runner Git SHA     : $HEAD_SHA"
echo "Evidence Git SHA   : $EXECUTION_GIT_SHA"
echo "Prepared-world root: $SOURCE_ROOT"
echo "Output             : $OUT"
echo "Scenes / dataset   : $SCENES_PER_DATASET"
echo "Reuse              : $REUSE"
echo "Analysis only      : $ANALYSIS_ONLY"
echo "Require COW        : $MAVEB_REQUIRE_COW"
echo "Min free disk      : $MIN_FREE_GIB GiB"
echo
"$PYTHON" "$STORAGE_DOCTOR" --repo "$ROOT" --minimum-free-gib 0 || true
echo
echo "Protocol:"
echo "  - exactly 5 deterministically ranked ready scenes per dataset"
echo "  - v5 algorithm, certificate, thresholds and edit magnitudes unchanged"
echo "  - 4 frozen locality profiles: smallest entity, ~1%, ~3%, broad ~12%"
echo "  - primary edit: opacity (delta-sensitive certificate)"
echo "  - control edit: translation (opacity-envelope certificate)"
echo "  - epsilon ladder: 1,2,4,8,16,32 / 255"
echo "  - residual ladder: exact, 1/4096, 1/1024, 1/256"
echo "  - primary statistics are scene-clustered; pooled case counts are secondary"
echo

if [[ "$ANALYSIS_ONLY" != "1" && -d "$CAMPAIGN/cases" ]]; then
  echo "Compacting already-completed v6 cases before the disk guard..."
  "$PYTHON" "$CASE_COMPACTOR" \
    --campaign-dir "$CAMPAIGN" \
    --execute
  echo
fi

if [[ "$ANALYSIS_ONLY" == "1" ]]; then
  echo
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "▶ [1-3/5] Analysis-only mode: reuse frozen v6 execution"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  for required in \
    "$FREEZE/reviewer-stress-campaign.json" \
    "$FREEZE/REVIEWER_STRESS_FREEZE.json" \
    "$CAMPAIGN/campaign-rows.jsonl" \
    "$CAMPAIGN/campaign-baselines.jsonl"; do
    if [[ ! -f "$required" ]]; then
      echo "Analysis-only prerequisite missing: $required" >&2
      echo "Run the full campaign once without MAVEB_REVIEWER_ANALYSIS_ONLY." >&2
      exit 5
    fi
  done
  echo "  ✓ reusing existing frozen campaign and completed case rows"
else
step 1 "Validate broad real-world prerequisites and build tools"
"$PYTHON" - "$WORLDS" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1])
m=json.loads(p.read_text())
if m.get("failedWorlds") or m.get("blockedWorlds"):
    raise SystemExit(
        f"broad worlds are not clean: ready={m.get('readyWorlds')} "
        f"failed={m.get('failedWorlds')} blocked={m.get('blockedWorlds')}"
    )
if int(m.get("readyWorlds",0)) < 2:
    raise SystemExit("at least two prepared worlds are required")
print(
    f"  ✓ broad worlds: {m['readyWorlds']} ready, "
    f"{m.get('nativePreparedWorlds',0)} native, "
    f"{m.get('rgbFallbackWorlds',0)} RGB fallback"
)
PY

cmake --preset "$BUILD_PRESET"
cmake --build --preset "$BUILD_PRESET"   --target maveb-cbrc-revision maveb-cbrc-gaussian-oracle   --parallel

if ! "$PYTHON" "$STORAGE_DOCTOR" --repo "$ROOT" --minimum-free-gib "$MIN_FREE_GIB"; then
  echo "Insufficient free disk for reviewer stress execution." >&2
  echo "Run: \"$PYTHON\" \"$STORAGE_DOCTOR\" --repo \"$ROOT\" --cleanup-safe --minimum-free-gib 0" >&2
  exit 3
fi

FREEZE_KEY="$("$PYTHON" "$CACHE_KEY"   --label confirmatory-breadth-freeze-v6   --file "$WORLDS"   --file "$CALIBRATION"   --file "$ROOT/benchmarks/scripts/cbrc_freeze_confirmatory_v6.py"   --file "$ROOT/benchmarks/scripts/cbrc_prepare_campaign_v2.py"   --file "$ROOT/benchmarks/scripts/cbrc_prepare_real_campaign.py"   --file "$ROOT/benchmarks/scripts/cbrc_storage.py"   --value "scenes_per_dataset=$SCENES_PER_DATASET")"

step 2 "Freeze reviewer-v6 confirmatory matrix"
if cache_hit freeze "$FREEZE_KEY"    && [[ -f "$FREEZE/reviewer-stress-campaign.json" ]]    && [[ -f "$FREEZE/REVIEWER_STRESS_FREEZE.json" ]]; then
  echo "  [██████████████████████████████] 100.00% | CACHE | reviewer matrix reused"
else
  rm -rf "$FREEZE"
  mkdir -p "$FREEZE"
  "$PYTHON" benchmarks/scripts/cbrc_freeze_confirmatory_v6.py     --worlds "$WORLDS"     --output-dir "$FREEZE"     --scenes-per-dataset "$SCENES_PER_DATASET"     --work-cost-model "$CALIBRATION"
  cache_done freeze "$FREEZE_KEY"
fi

CASE_COUNT="$("$PYTHON" - "$FREEZE/reviewer-stress-campaign.json" <<'PY'
import json,sys
from pathlib import Path
print(len(json.loads(Path(sys.argv[1]).read_text())["cases"]))
PY
)"
echo "  Frozen cases: $CASE_COUNT"

CAMPAIGN_ALREADY_COMPLETE="$("$PYTHON" - "$CAMPAIGN" "$CASE_COUNT" <<'PY'
import json,sys
from pathlib import Path

root=Path(sys.argv[1])
expected=int(sys.argv[2])
cases=root/"cases"

complete=0
if cases.is_dir():
    for case_dir in cases.iterdir():
        if not case_dir.is_dir():
            continue
        required=(
            case_dir/"CASE_COMPLETE.json",
            case_dir/"replay-manifest.json",
            case_dir/"revision-row.json",
            case_dir/"baselines.json",
        )
        if not all(path.is_file() for path in required):
            continue
        try:
            marker=json.loads((case_dir/"CASE_COMPLETE.json").read_text())
        except Exception:
            continue
        if marker.get("caseId") and marker.get("executionSignature"):
            complete += 1

aggregate_files=(
    root/"campaign-rows.jsonl",
    root/"campaign-baselines.jsonl",
    root/"campaign-timings.jsonl",
    root/"campaign-gates.json",
    root/"planner-parity.json",
    root/"baseline-summary.json",
    root/"campaign-evaluation.json",
)
aggregates_ok=all(path.is_file() for path in aggregate_files)

def line_count(path: Path) -> int:
    return sum(1 for line in path.read_text().splitlines() if line.strip())

rows_ok=(
    aggregates_ok
    and line_count(root/"campaign-rows.jsonl")==expected
    and line_count(root/"campaign-baselines.jsonl")==expected
    and line_count(root/"campaign-timings.jsonl")==expected
)
print("1" if complete==expected and rows_ok else "0")
PY
)"

step 3 "Execute unchanged v5 mechanism across frozen v6 scenes"
echo "  This step is resumable case-by-case."
echo "  If interrupted, rerun this script; completed matching cases are reused."

export MAVEB_ORACLE_CACHE_DIR="${MAVEB_ORACLE_CACHE_DIR:-$CAMPAIGN/.oracle-cache}"

if [[ "$CAMPAIGN_ALREADY_COMPLETE" == "1" ]]; then
  echo "  [██████████████████████████████] 100.00% | COMPLETE | 3840/3840 cases and canonical aggregates already present"
  echo "  ✓ skipping case execution; continuing directly to v6 audit/post-processing"
else

COMPACTOR_STOP="$CAMPAIGN/.case-compactor-stop"
rm -f "$COMPACTOR_STOP"
"$PYTHON" "$CASE_COMPACTOR" \
  --campaign-dir "$CAMPAIGN" \
  --execute \
  --watch \
  --interval-seconds 2 \
  --stop-file "$COMPACTOR_STOP" &
COMPACTOR_PID=$!

stop_case_compactor() {
  touch "$COMPACTOR_STOP"
  wait "$COMPACTOR_PID" 2>/dev/null || true
  rm -f "$COMPACTOR_STOP"
}
trap stop_case_compactor EXIT INT TERM

set +e
"$PYTHON" benchmarks/scripts/cbrc_campaign.py \
  --campaign "$FREEZE/reviewer-stress-campaign.json" \
  --freeze-provenance "$FREEZE/REVIEWER_STRESS_FREEZE.json" \
  --oracle "$ORACLE" \
  --revision-tool "$REVISION" \
  --git-sha "$EXECUTION_GIT_SHA" \
  --output-dir "$CAMPAIGN" \
  --resume \
  --invalidate-stale-resume \
  --workers "$CASE_WORKERS"
CAMPAIGN_STATUS=$?
set -e

stop_case_compactor
trap - EXIT INT TERM
if [[ "$CAMPAIGN_STATUS" -ne 0 ]]; then
  exit "$CAMPAIGN_STATUS"
fi

# One final pass catches cases that completed between the watcher's last poll
# and campaign finalization.
"$PYTHON" "$CASE_COMPACTOR" \
  --campaign-dir "$CAMPAIGN" \
  --execute
fi

fi

AUDIT_KEY="$("$PYTHON" "$CACHE_KEY"   --label confirmatory-breadth-audit-v6   --file "$FREEZE/reviewer-stress-campaign.json"   --file "$CAMPAIGN/campaign-rows.jsonl"   --file "$CAMPAIGN/campaign-baselines.jsonl"   --file "$ROOT/research/analysis/cbrc_reviewer_evidence_v3.py"   --file "$ROOT/research/analysis/cbrc_trace_case.py"   --file "$ROOT/research/analysis/cbrc_v5_certificate_analysis.py"   --file "$ROOT/research/analysis/cbrc_v6_breadth_analysis.py"   --file "$ROOT/research/analysis/cbrc_v6_manuscript_packet.py")"

step 4 "Audit certificate validity and scene-clustered confirmation"
if cache_hit audit "$AUDIT_KEY"    && [[ -f "$ANALYSIS/REVIEWER_EVIDENCE_AUDIT.json" ]]    && [[ -f "$ANALYSIS/V6_BREADTH_AUDIT.json" ]]    && [[ -f "$ANALYSIS/V6_MANUSCRIPT_CLAIMS.json" ]]    && [[ -f "$ANALYSIS/CASE_DECISION_TRACE.json" ]]; then
  echo "  [██████████████████████████████] 100.00% | CACHE | v6 audit reused"
else
  rm -rf "$ANALYSIS"
  mkdir -p "$ANALYSIS"
  "$PYTHON" research/analysis/cbrc_reviewer_evidence_v3.py     --campaign "$FREEZE/reviewer-stress-campaign.json"     --rows "$CAMPAIGN/campaign-rows.jsonl"     --output-dir "$ANALYSIS"
  "$PYTHON" research/analysis/cbrc_v6_breadth_analysis.py     --campaign "$FREEZE/reviewer-stress-campaign.json"     --rows "$CAMPAIGN/campaign-rows.jsonl"     --campaign-dir "$CAMPAIGN"     --baselines "$CAMPAIGN/campaign-baselines.jsonl"     --output-dir "$ANALYSIS"
  "$PYTHON" research/analysis/cbrc_v6_manuscript_packet.py     --audit "$ANALYSIS/V6_BREADTH_AUDIT.json"     --output-dir "$ANALYSIS"
  "$PYTHON" research/analysis/cbrc_trace_case.py     --rows "$CAMPAIGN/campaign-rows.jsonl"     --campaign-dir "$CAMPAIGN"     --output "$ANALYSIS/CASE_DECISION_TRACE.json" >/dev/null
  cache_done audit "$AUDIT_KEY"
fi

ROWS_KEY="$("$PYTHON" "$CACHE_KEY" --label confirmatory-breadth-rows-v6 --file "$CAMPAIGN/campaign-rows.jsonl")"
VISUAL_KEY="$("$PYTHON" "$CACHE_KEY" --label confirmatory-breadth-visuals-v6 --file "$IMPORT" --file "$ANALYSIS/REVIEWER_EVIDENCE_AUDIT.json" --file "$ROOT/research/analysis/cbrc_reviewer_visuals.py" --value "campaign_rows_sha=$ROWS_KEY")"

if ! "$PYTHON" - <<'PY'
try:
    import PIL  # noqa: F401
except ModuleNotFoundError:
    raise SystemExit(1)
PY
then
  echo "Reviewer figure generation requires Pillow in MAVEB_PYTHON." >&2
  echo "Install once with:" >&2
  echo "  \"$PYTHON\" -m pip install Pillow" >&2
  exit 4
fi

step 5 "Build real captured-scene reviewer figures"
if cache_hit visuals "$VISUAL_KEY"    && [[ -f "$VISUALS/REVIEWER_VISUALS.json" ]]; then
  echo "  [██████████████████████████████] 100.00% | CACHE | reviewer visuals reused"
else
  rm -rf "$VISUALS"
  mkdir -p "$VISUALS"
  "$PYTHON" "$VISUAL_REGEN" \
    --campaign "$FREEZE/reviewer-stress-campaign.json" \
    --campaign-dir "$CAMPAIGN" \
    --audit "$ANALYSIS/REVIEWER_EVIDENCE_AUDIT.json" \
    --import-manifest "$IMPORT" \
    --oracle "$ORACLE" \
    --revision-tool "$REVISION" \
    --freeze-provenance "$FREEZE/REVIEWER_STRESS_FREEZE.json" \
    --git-sha "$EXECUTION_GIT_SHA" \
    --limit 4
  "$PYTHON" research/analysis/cbrc_reviewer_visuals.py \
    --campaign-dir "$CAMPAIGN" \
    --audit "$ANALYSIS/REVIEWER_EVIDENCE_AUDIT.json" \
    --import-manifest "$IMPORT" \
    --output-dir "$VISUALS"
  # The rendered reviewer figures are now durable; compact the regenerated
  # per-case PPMs again.
  "$PYTHON" "$CASE_COMPACTOR" \
    --campaign-dir "$CAMPAIGN" \
    --execute
  cache_done visuals "$VISUAL_KEY"
fi

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "▶ v6 confirmatory evidence remains isolated from manuscript state"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  No researchpaper/generated reviewer state is written by this exploratory runner."
echo

"$PYTHON" - "$ANALYSIS/REVIEWER_EVIDENCE_AUDIT.json" "$ANALYSIS/V6_BREADTH_AUDIT.json" "$VISUALS/REVIEWER_VISUALS.json" <<'PY'
import json,sys
from pathlib import Path
audit=json.loads(Path(sys.argv[1]).read_text())
breadth=json.loads(Path(sys.argv[2]).read_text())
visuals=json.loads(Path(sys.argv[3]).read_text())
print()
print("============================================================")
print("MAVEB V6 CONFIRMATORY BREADTH SUMMARY")
print("============================================================")
print(f"{'independent scenes':38}: {breadth.get('sceneCount')}")
print(f"{'pooled parameter cases':38}: {breadth.get('pooledCaseCount')}")
print(f"{'confirmatoryPass':38}: {breadth.get('confirmatoryPass')}")
for name,passed in breadth["confirmatoryGates"].items():
    print(f"  {'PASS' if passed else 'OPEN':4}  {name}")
cluster=breadth["sceneClustered"]
paired=cluster["pairedOpacityMinusTranslationNonzeroLocalRate"]
print()
print(f"{'scene mean opacity-control delta':38}: {paired.get('mean')}")
print(f"{'scene-bootstrap 95% CI':38}: {paired.get('ci95')}")
print(f"{'scenes with nonzero opacity LOCAL':38}: {cluster.get('scenesWithNonzeroOpacityLocal')}")
print(f"{'scenes with opacity crossover':38}: {cluster.get('scenesWithOpacityCrossover')}")
print(f"{'pooled reviewer evidence ready':38}: {audit.get('reviewerEvidenceReady')}")
print(f"{'source RGB resolved figure cases':38}: "
      f"{visuals.get('casePanel',{}).get('sourceRgbResolvedCases')}")
PY

cat <<EOF

Artifacts:
  Campaign       : $FREEZE/reviewer-stress-campaign.json
  Rows           : $CAMPAIGN/campaign-rows.jsonl
  Baselines      : $CAMPAIGN/campaign-baselines.jsonl
  Generic audit  : $ANALYSIS/REVIEWER_EVIDENCE_AUDIT.json
  V6 audit       : $ANALYSIS/V6_BREADTH_AUDIT.json
  V6 audit MD    : $ANALYSIS/V6_BREADTH_AUDIT.md
  Scene metrics  : $ANALYSIS/V6_SCENE_METRICS.csv
  Baseline scenes: $ANALYSIS/V6_BASELINE_SCENE_METRICS.csv
  Claims JSON    : $ANALYSIS/V6_MANUSCRIPT_CLAIMS.json
  Manuscript MD  : $ANALYSIS/V6_MANUSCRIPT_PACKET.md
  Manuscript TeX : $ANALYSIS/V6_MANUSCRIPT_TABLES.tex
  Case trace     : $ANALYSIS/CASE_DECISION_TRACE.json
  Real scenes    : $VISUALS/F_REVIEWER_REAL_SCENE_LOCAL_VS_FULL.png
  Crossover      : $VISUALS/F_REVIEWER_TOLERANCE_CROSSOVER.png
  Visual index   : $VISUALS/REVIEWER_VISUALS.json
  v6 remains isolated from manuscript state until confirmatory gates pass.

Re-analyze an existing frozen v6 execution only:
  MAVEB_REVIEWER_ANALYSIS_ONLY=1 bash run_confirmatory_breadth_v6.sh

Resume/full execution:
  bash run_confirmatory_breadth_v6.sh

Scientific rule:
  v3/v4/v5 are immutable. v6 repeats the v5 mechanism without algorithm or threshold
  changes. Scene selection is deterministic and frozen; no failed scene or case may be
  removed, swapped, or retuned after execution begins.
EOF

if [[ "${MAVEB_FINAL_CLEANUP_AFTER_V6:-0}" == "1" ]]; then
  echo
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "▶ Final MAVEB cleanup requested"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  "$PYTHON" maintenance/final_cleanup.py \
    --repo "$ROOT" \
    --execute \
    --i-understand-this-deletes-data
fi
