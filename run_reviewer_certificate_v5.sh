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
OUT="${MAVEB_REVIEWER_V5_RESULTS_DIR:-$ROOT/build/reviewer-certificate-v5}"
SCENES_PER_DATASET="${MAVEB_REVIEWER_SCENES_PER_DATASET:-1}"
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
export MAVEB_REQUIRE_COW="${MAVEB_REQUIRE_COW:-1}"
MIN_FREE_GIB="${MAVEB_MIN_FREE_GIB:-5}"

mkdir -p "$FREEZE" "$CAMPAIGN" "$ANALYSIS" "$VISUALS" "$CACHE"

for required in "$WORLDS" "$CALIBRATION" "$IMPORT"; do
  if [[ ! -f "$required" ]]; then
    echo "Missing prerequisite: $required" >&2
    echo "Complete/adopt the broad smoke campaign first." >&2
    exit 2
  fi
done

HEAD_SHA="$(git rev-parse HEAD)"

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
echo "MAVEB reviewer-v5 opacity-delta certificate campaign"
echo "============================================================"
echo "Git SHA            : $HEAD_SHA"
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
echo "  - deterministic real-world selection"
echo "  - 4 frozen locality profiles: smallest entity, ~1%, ~3%, broad ~12%"
echo "  - primary edit: opacity (new delta-sensitive certificate)"
echo "  - control edit: translation (old opacity-envelope certificate)"
echo "  - epsilon ladder: 1,2,4,8,16,32 / 255"
echo "  - residual ladder: exact, 1/4096, 1/1024, 1/256"
echo "  - v3/v4 evidence is immutable; this is a separate outcome-blind v5 freeze"
echo

if [[ "$ANALYSIS_ONLY" == "1" ]]; then
  echo
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "▶ [1-3/5] Analysis-only mode: reuse frozen v5 execution"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  for required in \
    "$FREEZE/reviewer-stress-campaign.json" \
    "$FREEZE/REVIEWER_STRESS_FREEZE.json" \
    "$CAMPAIGN/campaign-rows.jsonl"; do
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

FREEZE_KEY="$("$PYTHON" "$CACHE_KEY"   --label reviewer-certificate-freeze-v5   --file "$WORLDS"   --file "$CALIBRATION"   --file "$ROOT/benchmarks/scripts/cbrc_freeze_reviewer_certificate_v5.py"   --file "$ROOT/benchmarks/scripts/cbrc_prepare_campaign_v2.py"   --file "$ROOT/benchmarks/scripts/cbrc_prepare_real_campaign.py"   --file "$ROOT/benchmarks/scripts/cbrc_storage.py"   --value "scenes_per_dataset=$SCENES_PER_DATASET")"

step 2 "Freeze reviewer-v5 certificate matrix"
if cache_hit freeze "$FREEZE_KEY"    && [[ -f "$FREEZE/reviewer-stress-campaign.json" ]]    && [[ -f "$FREEZE/REVIEWER_STRESS_FREEZE.json" ]]; then
  echo "  [██████████████████████████████] 100.00% | CACHE | reviewer matrix reused"
else
  rm -rf "$FREEZE"
  mkdir -p "$FREEZE"
  "$PYTHON" benchmarks/scripts/cbrc_freeze_reviewer_certificate_v5.py     --worlds "$WORLDS"     --output-dir "$FREEZE"     --scenes-per-dataset "$SCENES_PER_DATASET"     --work-cost-model "$CALIBRATION"
  cache_done freeze "$FREEZE_KEY"
fi

CASE_COUNT="$("$PYTHON" - "$FREEZE/reviewer-stress-campaign.json" <<'PY'
import json,sys
from pathlib import Path
print(len(json.loads(Path(sys.argv[1]).read_text())["cases"]))
PY
)"
echo "  Frozen cases: $CASE_COUNT"

step 3 "Execute oracle-checked reviewer-v5 cases"
echo "  This step is resumable case-by-case."
echo "  If interrupted, rerun this script; completed matching cases are reused."

export MAVEB_ORACLE_CACHE_DIR="${MAVEB_ORACLE_CACHE_DIR:-$CAMPAIGN/.oracle-cache}"
"$PYTHON" benchmarks/scripts/cbrc_campaign.py   --campaign "$FREEZE/reviewer-stress-campaign.json"   --freeze-provenance "$FREEZE/REVIEWER_STRESS_FREEZE.json"   --oracle "$ORACLE"   --revision-tool "$REVISION"   --git-sha "$HEAD_SHA"   --output-dir "$CAMPAIGN"   --resume   --invalidate-stale-resume   --workers "$CASE_WORKERS"

fi

AUDIT_KEY="$("$PYTHON" "$CACHE_KEY"   --label reviewer-certificate-audit-v5   --file "$FREEZE/reviewer-stress-campaign.json"   --file "$CAMPAIGN/campaign-rows.jsonl"   --file "$ROOT/research/analysis/cbrc_reviewer_evidence_v3.py"   --file "$ROOT/research/analysis/cbrc_trace_case.py"   --file "$ROOT/research/analysis/cbrc_v5_certificate_analysis.py")"

step 4 "Audit certificate validity, routing, scaling, and planner outcomes"
if cache_hit audit "$AUDIT_KEY"    && [[ -f "$ANALYSIS/REVIEWER_EVIDENCE_AUDIT.json" ]]    && [[ -f "$ANALYSIS/V5_CERTIFICATE_AUDIT.json" ]]    && [[ -f "$ANALYSIS/CASE_DECISION_TRACE.json" ]]; then
  echo "  [██████████████████████████████] 100.00% | CACHE | v5 audit reused"
else
  rm -rf "$ANALYSIS"
  mkdir -p "$ANALYSIS"
  "$PYTHON" research/analysis/cbrc_reviewer_evidence_v3.py     --campaign "$FREEZE/reviewer-stress-campaign.json"     --rows "$CAMPAIGN/campaign-rows.jsonl"     --output-dir "$ANALYSIS"
  "$PYTHON" research/analysis/cbrc_v5_certificate_analysis.py     --campaign "$FREEZE/reviewer-stress-campaign.json"     --rows "$CAMPAIGN/campaign-rows.jsonl"     --campaign-dir "$CAMPAIGN"     --output-dir "$ANALYSIS"
  "$PYTHON" research/analysis/cbrc_trace_case.py     --rows "$CAMPAIGN/campaign-rows.jsonl"     --campaign-dir "$CAMPAIGN"     --output "$ANALYSIS/CASE_DECISION_TRACE.json" >/dev/null
  cache_done audit "$AUDIT_KEY"
fi

ROWS_KEY="$("$PYTHON" "$CACHE_KEY" --label reviewer-certificate-rows-v5 --file "$CAMPAIGN/campaign-rows.jsonl")"
VISUAL_KEY="$("$PYTHON" "$CACHE_KEY" --label reviewer-certificate-visuals-v5 --file "$IMPORT" --file "$ANALYSIS/REVIEWER_EVIDENCE_AUDIT.json" --file "$ROOT/research/analysis/cbrc_reviewer_visuals.py" --value "campaign_rows_sha=$ROWS_KEY")"

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
  "$PYTHON" research/analysis/cbrc_reviewer_visuals.py     --campaign-dir "$CAMPAIGN"     --audit "$ANALYSIS/REVIEWER_EVIDENCE_AUDIT.json"     --import-manifest "$IMPORT"     --output-dir "$VISUALS"
  cache_done visuals "$VISUAL_KEY"
fi

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "▶ v5 certificate evidence remains isolated from manuscript state"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  No researchpaper/generated reviewer state is written by this exploratory runner."
echo

"$PYTHON" - "$ANALYSIS/REVIEWER_EVIDENCE_AUDIT.json" "$ANALYSIS/V5_CERTIFICATE_AUDIT.json" "$VISUALS/REVIEWER_VISUALS.json" <<'PY'
import json,sys
from pathlib import Path
audit=json.loads(Path(sys.argv[1]).read_text())
cert=json.loads(Path(sys.argv[2]).read_text())
visuals=json.loads(Path(sys.argv[3]).read_text())
print()
print("============================================================")
print("REVIEWER V5 CERTIFICATE SUMMARY")
print("============================================================")
print(f"{'recordCount':34}: {cert.get('recordCount')}")
print(f"{'certificateExperimentValid':34}: {cert.get('certificateExperimentValid')}")
for name,passed in cert["validityGates"].items():
    print(f"  {'PASS' if passed else 'OPEN':4}  {name}")
print()
for family,item in cert["byEditFamily"].items():
    print(
        f"{family:12}: {item['localCases']} LOCAL / "
        f"{item['fullFallbackCases']} FULL | "
        f"nonzero LOCAL={item['nonzeroLocalCases']} | "
        f"crossovers={item['crossoverStressKeys']}"
    )
print()
print(f"{'legacyReviewerEvidenceReady':34}: {audit.get('reviewerEvidenceReady')}")
print(f"{'sourceRgbResolvedCases':34}: "
      f"{visuals.get('casePanel',{}).get('sourceRgbResolvedCases')}")
if not cert["certificateExperimentValid"]:
    print("The v5 certificate experiment has an OPEN validity gate. Do not promote it.")
PY

cat <<EOF

Artifacts:
  Campaign       : $FREEZE/reviewer-stress-campaign.json
  Rows           : $CAMPAIGN/campaign-rows.jsonl
  Generic audit  : $ANALYSIS/REVIEWER_EVIDENCE_AUDIT.json
  V5 audit       : $ANALYSIS/V5_CERTIFICATE_AUDIT.json
  V5 audit MD    : $ANALYSIS/V5_CERTIFICATE_AUDIT.md
  Case trace     : $ANALYSIS/CASE_DECISION_TRACE.json
  Real scenes    : $VISUALS/F_REVIEWER_REAL_SCENE_LOCAL_VS_FULL.png
  Crossover      : $VISUALS/F_REVIEWER_TOLERANCE_CROSSOVER.png
  Visual index   : $VISUALS/REVIEWER_VISUALS.json
  v5 certificate evidence is intentionally not connected to manuscript state yet.

Re-analyze an existing frozen v5 execution only:
  MAVEB_REVIEWER_ANALYSIS_ONLY=1 bash run_reviewer_certificate_v5.sh

Resume/full execution:
  bash run_reviewer_certificate_v5.sh

Force a fresh v5 certificate run:
  MAVEB_REVIEWER_REUSE=0 bash run_reviewer_certificate_v5.sh

Scientific rule:
  v3/v4 remain immutable. An OPEN v5 gate is reported, not hidden by post-hoc
  deletion, epsilon retuning, residual retuning, or selection of favorable cases.
EOF
