#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON="${MAVEB_PYTHON:-python3}"
LAUNCH_STUDIO=0

usage() {
  cat <<'EOF'
MAVEB repository-wide build, test, validation, and execution driver

Usage:
  ./run_all.sh [--launch-studio] [--help]

Always runs:
  1. environment/provenance report
  2. repository whitespace check
  3. warnings-as-errors CI configure/build/CTest
  4. sanitizer configure/build/CTest
  5. macOS AetherStudio debug compile
  6. MavebBench Python unit tests
  7. research Python unit tests
  8. 100,000-trial Gaussian+temporal certificate falsification
  9. synthetic CBRC phase-behavior pilot
 10. optional frozen real campaign

Options:
  --launch-studio
      Open AetherStudio after all validation passes.

Environment:
  MAVEB_PYTHON=/path/to/python
      Python interpreter to use. bootstrap_and_run.sh sets this to the
      repository virtual environment automatically.

  MAVEB_CAMPAIGN=/absolute/path/campaign.json
      If set, execute the frozen real captured-world campaign after all
      repository-contained gates pass.

  MAVEB_WORK_COST=/absolute/path/frozen-work-cost.json
      Optional explicit frozen work-cost file existence check.

  MAVEB_RESULTS_DIR=/absolute/path/results
      Output directory for generated validation artifacts.
      Default: build/research-final

Important:
  Real-scene publication evidence requires the external archives/sidecars
  referenced by MAVEB_CAMPAIGN. If no real campaign is supplied, this script
  reports that phase as pending rather than fabricating results.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --launch-studio)
      LAUNCH_STUDIO=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

command -v git >/dev/null 2>&1 || { echo "git is required" >&2; exit 2; }
command -v cmake >/dev/null 2>&1 || { echo "cmake is required" >&2; exit 2; }
command -v ninja >/dev/null 2>&1 || { echo "ninja is required" >&2; exit 2; }
command -v "$PYTHON" >/dev/null 2>&1 || { echo "Python interpreter not found: $PYTHON" >&2; exit 2; }

RESULTS_DIR="${MAVEB_RESULTS_DIR:-$ROOT/build/research-final}"
RESEARCH_BUILD_PRESET="${MAVEB_RESEARCH_BUILD_PRESET:-research}"
RESEARCH_BUILD_ROOT="$ROOT/build/$RESEARCH_BUILD_PRESET"
CASE_WORKERS="${MAVEB_CASE_WORKERS:-4}"
mkdir -p "$RESULTS_DIR"

echo "============================================================"
echo "MAVEB / CBRC complete verification"
echo "============================================================"
echo "Repository : $ROOT"
echo "Git SHA    : $(git rev-parse HEAD)"
echo "Branch     : $(git branch --show-current || true)"
echo "OS         : $(uname -s) $(uname -m)"
if command -v sw_vers >/dev/null 2>&1; then
  echo "macOS      : $(sw_vers -productVersion)"
fi
echo "CMake      : $(cmake --version | head -n 1)"
echo "Ninja      : $(ninja --version)"
echo "Python     : $("$PYTHON" --version 2>&1)"
if command -v xcodebuild >/dev/null 2>&1; then
  echo "Xcode      : $(xcodebuild -version | tr '\n' ' ')"
fi
echo "Results    : $RESULTS_DIR"
echo

echo "==> [1/10] Repository whitespace validation"
git diff --check
git diff --cached --check

echo "==> [2/10] Warnings-as-errors CI configure/build/tests"
cmake --preset ci
cmake --build --preset ci --parallel
ctest --preset ci

echo "==> [3/10] Sanitizer configure/build/tests"
cmake --preset sanitizer
cmake --build --preset sanitizer --parallel
ctest --test-dir build/sanitizer --output-on-failure

echo "==> [4/10] AetherStudio debug compile"
cmake --preset debug -DAETHER_REQUIRE_METAL_TOOLCHAIN=OFF
cmake --build --preset debug --target AetherStudio --parallel

echo "==> [5/10] MavebBench Python tests"
"$PYTHON" -m unittest discover -s benchmarks/tests -p 'test_*.py'

echo "==> [6/10] Research Python tests"
"$PYTHON" -m unittest discover -s research/tests -p 'test_*.py'

echo "==> [7/10] Randomized Gaussian + temporal certificate falsification"
"$PYTHON" research/experiments/cbrc_gaussian_temporal_chain.py \
  --seed 20260920 \
  --trials 100000

echo "==> [8/10] Synthetic CBRC pilot"
"$PYTHON" research/experiments/cbrc_synthetic_benchmark.py \
  --out "$RESULTS_DIR/cbrc-synthetic-pilot.jsonl" \
  --seed 20260920 \
  --repeats 1 \
  --pilot

echo "==> [9/10] Native tool smoke validation"
for tool in \
  build/ci/tools/maveb-cbrc-revision/maveb-cbrc-revision \
  build/ci/tools/maveb-cbrc-gaussian-oracle/maveb-cbrc-gaussian-oracle; do
  if [[ ! -x "$tool" ]]; then
    echo "Expected native tool was not built: $tool" >&2
    exit 4
  fi
done
echo "Native CBRC revision and full-reference oracle binaries are present."

echo "==> [10/10] Frozen real campaign"
if [[ -n "${MAVEB_CAMPAIGN:-}" ]]; then
  [[ -f "$MAVEB_CAMPAIGN" ]] || {
    echo "MAVEB_CAMPAIGN does not exist: $MAVEB_CAMPAIGN" >&2
    exit 3
  }
  if [[ -n "${MAVEB_WORK_COST:-}" && ! -f "$MAVEB_WORK_COST" ]]; then
    echo "MAVEB_WORK_COST does not exist: $MAVEB_WORK_COST" >&2
    exit 3
  fi

  echo "Building optimized research binaries for the external real campaign."
  cmake --preset "$RESEARCH_BUILD_PRESET"
  cmake --build --preset "$RESEARCH_BUILD_PRESET" --target \
    maveb-cbrc-revision maveb-cbrc-gaussian-oracle --parallel
  export MAVEB_CASE_WORKERS="$CASE_WORKERS"
  export MAVEB_ORACLE_BACKEND="${MAVEB_ORACLE_BACKEND:-cpu}"
  export MAVEB_ORACLE_CACHE_DIR="${MAVEB_ORACLE_CACHE_DIR:-$RESULTS_DIR/real-campaign/.oracle-cache}"

  "$PYTHON" benchmarks/scripts/cbrc_campaign.py \
    --campaign "$MAVEB_CAMPAIGN" \
    --oracle "$RESEARCH_BUILD_ROOT/tools/maveb-cbrc-gaussian-oracle/maveb-cbrc-gaussian-oracle" \
    --revision-tool "$RESEARCH_BUILD_ROOT/tools/maveb-cbrc-revision/maveb-cbrc-revision" \
    --git-sha "$(git rev-parse HEAD)" \
    --output-dir "$RESULTS_DIR/real-campaign" \
    --workers "$CASE_WORKERS"

  echo "Real campaign completed. Inspect campaign-gates.json before interpreting performance."
else
  echo "SKIP: no MAVEB_CAMPAIGN supplied."
  echo "All repository-contained engineering/theorem/synthetic gates passed;"
  echo "real captured-scene publication evidence remains an external-data phase."
fi

if (( LAUNCH_STUDIO )); then
  APP="$ROOT/build/debug/apps/AetherStudio/AetherStudio.app"
  if [[ ! -d "$APP" ]]; then
    echo "AetherStudio bundle was not produced at: $APP" >&2
    exit 5
  fi
  echo "==> Launching AetherStudio"
  open "$APP"
fi

echo
echo "============================================================"
echo "MAVEB verification complete"
echo "SHA: $(git rev-parse HEAD)"
echo "Artifacts: $RESULTS_DIR"
echo "============================================================"
