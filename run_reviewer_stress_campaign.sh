#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

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
OUT="${MAVEB_REVIEWER_RESULTS_DIR:-$ROOT/build/reviewer-stress}"
SCENES_PER_DATASET="${MAVEB_REVIEWER_SCENES_PER_DATASET:-1}"
REUSE="${MAVEB_REVIEWER_REUSE:-1}"

WORLDS="$SOURCE_ROOT/worlds/BROAD_WORLDS.json"
CALIBRATION="$SOURCE_ROOT/calibration/work-cost-model.json"
IMPORT="$SOURCE_ROOT/import/BROAD_IMPORT.json"
FREEZE="$OUT/frozen"
CAMPAIGN="$OUT/campaign"
ANALYSIS="$OUT/analysis"
VISUALS="$OUT/visuals"
CACHE="$OUT/.stage-cache"

REVISION="$ROOT/build/ci/tools/maveb-cbrc-revision/maveb-cbrc-revision"
ORACLE="$ROOT/build/ci/tools/maveb-cbrc-gaussian-oracle/maveb-cbrc-gaussian-oracle"
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
echo "MAVEB post-reviewer practical-evidence campaign"
echo "============================================================"
echo "Git SHA            : $HEAD_SHA"
echo "Prepared-world root: $SOURCE_ROOT"
echo "Output             : $OUT"
echo "Scenes / dataset   : $SCENES_PER_DATASET"
echo "Reuse              : $REUSE"
echo "Require COW        : $MAVEB_REQUIRE_COW"
echo "Min free disk      : $MIN_FREE_GIB GiB"
echo
"$PYTHON" "$STORAGE_DOCTOR" --repo "$ROOT" --minimum-free-gib 0 || true
echo
echo "Protocol:"
echo "  - deterministic real-world selection"
echo "  - 2 fixed edit-severity profiles"
echo "  - translation / rotation / scale / opacity"
echo "  - epsilon ladder: 0.25,0.5,1,2,4,8,16 / 255"
echo "  - within each stress key, epsilon is the ONLY changed variable"
echo

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

cmake --preset ci
cmake --build --preset ci   --target maveb-cbrc-revision maveb-cbrc-gaussian-oracle   --parallel

if ! "$PYTHON" "$STORAGE_DOCTOR" --repo "$ROOT" --minimum-free-gib "$MIN_FREE_GIB"; then
  echo "Insufficient free disk for reviewer stress execution." >&2
  echo "Run: \"$PYTHON\" \"$STORAGE_DOCTOR\" --repo \"$ROOT\" --cleanup-safe --minimum-free-gib 0" >&2
  exit 3
fi

FREEZE_KEY="$("$PYTHON" "$CACHE_KEY"   --label reviewer-stress-freeze-v1   --file "$WORLDS"   --file "$CALIBRATION"   --file "$ROOT/benchmarks/scripts/cbrc_freeze_reviewer_stress.py"   --file "$ROOT/benchmarks/scripts/cbrc_prepare_campaign_v2.py"   --file "$ROOT/benchmarks/scripts/cbrc_prepare_real_campaign.py"   --file "$ROOT/benchmarks/scripts/cbrc_storage.py"   --value "scenes_per_dataset=$SCENES_PER_DATASET")"

step 2 "Freeze reviewer tolerance-crossover matrix"
if cache_hit freeze "$FREEZE_KEY"    && [[ -f "$FREEZE/reviewer-stress-campaign.json" ]]    && [[ -f "$FREEZE/REVIEWER_STRESS_FREEZE.json" ]]; then
  echo "  [██████████████████████████████] 100.00% | CACHE | reviewer matrix reused"
else
  rm -rf "$FREEZE"
  mkdir -p "$FREEZE"
  "$PYTHON" benchmarks/scripts/cbrc_freeze_reviewer_stress.py     --worlds "$WORLDS"     --output-dir "$FREEZE"     --scenes-per-dataset "$SCENES_PER_DATASET"     --work-cost-model "$CALIBRATION"
  cache_done freeze "$FREEZE_KEY"
fi

CASE_COUNT="$("$PYTHON" - "$FREEZE/reviewer-stress-campaign.json" <<'PY'
import json,sys
from pathlib import Path
print(len(json.loads(Path(sys.argv[1]).read_text())["cases"]))
PY
)"
echo "  Frozen cases: $CASE_COUNT"

step 3 "Execute oracle-checked reviewer stress cases"
echo "  This step is resumable case-by-case."
echo "  If interrupted, rerun this script; completed matching cases are reused."

"$PYTHON" benchmarks/scripts/cbrc_campaign.py   --campaign "$FREEZE/reviewer-stress-campaign.json"   --freeze-provenance "$FREEZE/REVIEWER_STRESS_FREEZE.json"   --oracle "$ORACLE"   --revision-tool "$REVISION"   --git-sha "$HEAD_SHA"   --output-dir "$CAMPAIGN"   --resume

AUDIT_KEY="$("$PYTHON" "$CACHE_KEY"   --label reviewer-evidence-audit-v1   --file "$FREEZE/reviewer-stress-campaign.json"   --file "$CAMPAIGN/campaign-rows.jsonl"   --file "$ROOT/research/analysis/cbrc_reviewer_evidence.py")"

step 4 "Analyze non-zero certified residuals and FULL-to-LOCAL crossovers"
if cache_hit audit "$AUDIT_KEY"    && [[ -f "$ANALYSIS/REVIEWER_EVIDENCE_AUDIT.json" ]]; then
  echo "  [██████████████████████████████] 100.00% | CACHE | reviewer audit reused"
else
  rm -rf "$ANALYSIS"
  mkdir -p "$ANALYSIS"
  "$PYTHON" research/analysis/cbrc_reviewer_evidence.py     --campaign "$FREEZE/reviewer-stress-campaign.json"     --rows "$CAMPAIGN/campaign-rows.jsonl"     --output-dir "$ANALYSIS"
  cache_done audit "$AUDIT_KEY"
fi

ROWS_KEY="$("$PYTHON" "$CACHE_KEY" --label reviewer-rows-v1 --file "$CAMPAIGN/campaign-rows.jsonl")"
VISUAL_KEY="$("$PYTHON" "$CACHE_KEY" --label reviewer-visual-package-v1 --file "$IMPORT" --file "$ANALYSIS/REVIEWER_EVIDENCE_AUDIT.json" --file "$ROOT/research/analysis/cbrc_reviewer_visuals.py" --value "campaign_rows_sha=$ROWS_KEY")"

step 5 "Build real captured-scene reviewer figures"
if cache_hit visuals "$VISUAL_KEY"    && [[ -f "$VISUALS/REVIEWER_VISUALS.json" ]]; then
  echo "  [██████████████████████████████] 100.00% | CACHE | reviewer visuals reused"
else
  rm -rf "$VISUALS"
  mkdir -p "$VISUALS"
  "$PYTHON" research/analysis/cbrc_reviewer_visuals.py     --campaign-dir "$CAMPAIGN"     --audit "$ANALYSIS/REVIEWER_EVIDENCE_AUDIT.json"     --import-manifest "$IMPORT"     --output-dir "$VISUALS"
  cache_done visuals "$VISUAL_KEY"
fi

"$PYTHON" - "$ANALYSIS/REVIEWER_EVIDENCE_AUDIT.json" "$VISUALS/REVIEWER_VISUALS.json" <<'PY'
import json,sys
from pathlib import Path
audit=json.loads(Path(sys.argv[1]).read_text())
visuals=json.loads(Path(sys.argv[2]).read_text())
print()
print("============================================================")
print("REVIEWER EVIDENCE SUMMARY")
print("============================================================")
for key in (
    "recordCount",
    "localCases",
    "fullFallbackCases",
    "certifiedNonzeroLocalCases",
    "nearBoundaryLocalCases",
    "toleranceCrossoverGroups",
    "dynamicCapturedSceneCandidates",
):
    print(f"{key:32}: {audit.get(key)}")
print(f"{'nonzeroLocalDatasets':32}: {audit.get('nonzeroLocalDatasets')}")
print(f"{'reviewerEvidenceReady':32}: {audit.get('reviewerEvidenceReady')}")
print(f"{'sourceRgbResolvedCases':32}: "
      f"{visuals.get('casePanel',{}).get('sourceRgbResolvedCases')}")
print()
for name,passed in audit["readinessGates"].items():
    print(f"  {'PASS' if passed else 'OPEN':4}  {name}")
print()
if not audit["reviewerEvidenceReady"]:
    print(
        "The frozen run remains valid, but one or more practical-review "
        "evidence targets remain OPEN. Do not delete or retune cases."
    )
PY

cat <<EOF

Artifacts:
  Campaign     : $FREEZE/reviewer-stress-campaign.json
  Rows         : $CAMPAIGN/campaign-rows.jsonl
  Audit        : $ANALYSIS/REVIEWER_EVIDENCE_AUDIT.json
  Audit MD     : $ANALYSIS/REVIEWER_EVIDENCE_AUDIT.md
  Real scenes  : $VISUALS/F_REVIEWER_REAL_SCENE_LOCAL_VS_FULL.png
  Crossover    : $VISUALS/F_REVIEWER_TOLERANCE_CROSSOVER.png
  Visual index : $VISUALS/REVIEWER_VISUALS.json

Resume:
  bash run_reviewer_stress_campaign.sh

Force a fresh reviewer run:
  MAVEB_REVIEWER_REUSE=0 bash run_reviewer_stress_campaign.sh

Scientific rule:
  An OPEN reviewer-evidence gate is reported, not hidden by post-hoc case
  deletion, epsilon retuning, or selection of only favorable outcomes.
EOF
