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

mkdir -p "$IMPORT_DIR" "$WORLDS_DIR" "$CAL_DIR" "$FREEZE_DIR" "$RESULTS_DIR" "$VISUAL_DIR" "$STATS_DIR"

REVISION="$ROOT/build/ci/tools/maveb-cbrc-revision/maveb-cbrc-revision"
ORACLE="$ROOT/build/ci/tools/maveb-cbrc-gaussian-oracle/maveb-cbrc-gaussian-oracle"
WORK_BENCH="$ROOT/build/ci/tools/maveb-cbrc-work-bench/maveb-cbrc-work-bench"
TRAINED_SEED="$ROOT/build/ci/tools/maveb-seed-trained-3dgs-world/maveb-seed-trained-3dgs-world"

echo "============================================================"
echo "MAVEB CBRC broad cross-dataset campaign"
echo "============================================================"
echo "Repository : $ROOT"
echo "Git SHA    : $(git rev-parse HEAD)"
echo "Output     : $OUT"
echo "Datasets   : $DATASETS_CSV"
echo

echo "==> [1/9] Validating/importing selected datasets"
"$PYTHON" benchmarks/scripts/cbrc_broad_benchmark.py import   --output "$IMPORT_DIR/BROAD_IMPORT.json"   "${DATASET_ARGS[@]}"

echo "==> [2/9] Building CBRC research tools"
cmake --preset ci
cmake --build --preset ci   --target     maveb-cbrc-revision     maveb-cbrc-gaussian-oracle     maveb-cbrc-work-bench     maveb-seed-trained-3dgs-world   --parallel

echo "==> [3/9] Preparing normalized persistent worlds"
"$PYTHON" benchmarks/scripts/cbrc_prepare_broad_worlds.py   --import-manifest "$IMPORT_DIR/BROAD_IMPORT.json"   --output-dir "$WORLDS_DIR"   --trained-seeder "$TRAINED_SEED"   "${DATASET_ARGS[@]}"   --max-images "${MAVEB_BROAD_MAX_IMAGES:-120}"

"$PYTHON" - "$WORLDS_DIR/BROAD_WORLDS.json" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]))
if p["failedWorlds"]:
    raise SystemExit(f"world preparation has {p['failedWorlds']} failed world(s)")
if p["readyWorlds"] < 2:
    raise SystemExit("need at least two prepared worlds for a broad campaign")
blocked=p["blockedWorlds"]
if blocked:
    raise SystemExit(f"selected dataset preparation left {blocked} blocked world record(s)")
print(f"prepared {p['readyWorlds']} worlds")
PY

echo "==> [4/9] Freezing one hardware work calibration"
CAL_ID="broad-$(uname -m)-$(git rev-parse --short=12 HEAD)"
"$WORK_BENCH"   --gaussians "${MAVEB_CAL_GAUSSIANS:-1000000}"   --publication-bytes "${MAVEB_CAL_PUBLICATION_BYTES:-268435456}"   --pixels "${MAVEB_CAL_PIXELS:-921600}"   --repeats "${MAVEB_CAL_REPEATS:-9}"   --calibration-id "$CAL_ID"   > "$CAL_DIR/calibration-rows.jsonl"

"$PYTHON" benchmarks/scripts/cbrc_calibrate_work.py   --input "$CAL_DIR/calibration-rows.jsonl"   --version "$CAL_ID"   --minimum-repeats 5   --output "$CAL_DIR/work-cost-model.json"   > "$CAL_DIR/work-cost-model.stdout.json"

echo "==> [5/9] Freezing cross-dataset cases before reading outcomes"
rm -rf "$FREEZE_DIR"
mkdir -p "$FREEZE_DIR"
"$PYTHON" benchmarks/scripts/cbrc_freeze_broad_campaign.py   --worlds "$WORLDS_DIR/BROAD_WORLDS.json"   --output-dir "$FREEZE_DIR"   --cases-per-scene "${MAVEB_BROAD_CASES_PER_SCENE:-15}"   --work-cost-model "$CAL_DIR/work-cost-model.json"   "${DATASET_ARGS[@]}"

echo "==> [6/9] Executing CBRC + oracle + baselines + ablations"
rm -rf "$RESULTS_DIR"
mkdir -p "$RESULTS_DIR"
"$PYTHON" benchmarks/scripts/cbrc_campaign.py   --campaign "$FREEZE_DIR/broad-campaign.json"   --oracle "$ORACLE"   --revision-tool "$REVISION"   --git-sha "$(git rev-parse HEAD)"   --output-dir "$RESULTS_DIR"

echo "==> [7/9] Measuring selected-render fidelity against FULL-after"
rm -rf "$VISUAL_DIR"
mkdir -p "$VISUAL_DIR"
"$PYTHON" research/analysis/cbrc_visual_quality.py   --campaign-dir "$RESULTS_DIR"   --output-dir "$VISUAL_DIR"

echo "==> [8/9] Computing cross-dataset statistics"
rm -rf "$STATS_DIR"
mkdir -p "$STATS_DIR"
"$PYTHON" research/analysis/cbrc_cross_dataset_statistics.py   --rows "$RESULTS_DIR/campaign-rows.jsonl"   --baselines "$RESULTS_DIR/campaign-baselines.jsonl"   --output-dir "$STATS_DIR"   --bootstrap-iterations "${MAVEB_BROAD_BOOTSTRAP_ITERATIONS:-5000}"

echo "==> [9/9] Writing campaign completion manifest"
"$PYTHON" - "$OUT" "$DATASETS_CSV" "$(git rev-parse HEAD)" <<'PY'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve()
datasets=sys.argv[2].split(",")
git_sha=sys.argv[3]
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
    root/"visual-quality/CBRC_VISUAL_QUALITY.json",
    root/"statistics/CROSS_DATASET_STATISTICS.json",
]
def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()
missing=[str(p) for p in files if not p.is_file()]
if missing: raise SystemExit("missing final evidence:\n" + "\n".join(missing))
manifest={
  "schemaVersion":1,
  "artifact":"maveb-cbrc-broad-campaign-completion",
  "gitSha":git_sha,
  "datasets":datasets,
  "files":[{"path":str(p.relative_to(root)),"sha256":sha(p),"bytes":p.stat().st_size} for p in files],
}
(root/"BROAD_CAMPAIGN_COMPLETE.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
print(json.dumps(manifest,indent=2,sort_keys=True))
PY

cat <<EOF

BROAD MAVEB CAMPAIGN COMPLETE

Import manifest    : $IMPORT_DIR/BROAD_IMPORT.json
Prepared worlds    : $WORLDS_DIR/BROAD_WORLDS.json
Frozen campaign    : $FREEZE_DIR/broad-campaign.json
Campaign rows      : $RESULTS_DIR/campaign-rows.jsonl
Visual fidelity    : $VISUAL_DIR/CBRC_VISUAL_QUALITY.json
Statistics         : $STATS_DIR/CROSS_DATASET_STATISTICS.json
Completion manifest: $OUT/BROAD_CAMPAIGN_COMPLETE.json

Scientific boundary:
  * one frozen CBRC implementation and one work calibration are used across selected datasets;
  * current broad algorithmic edit family is translation only;
  * dataset-specific import/coordinate conversion is provenance, not threshold retuning;
  * failed/FULL cases remain evidence;
  * this is cross-dataset empirical validation, not universal proof.
EOF
