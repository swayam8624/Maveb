#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

usage() {
  cat <<'EOF'
MAVEB repository-wide verification

Usage:
  ./run_all.sh [--help]

Always runs:
  1. git whitespace validation
  2. CI configure/build/CTest
  3. sanitizer configure/build/CTest
  4. MavebBench Python unit tests
  5. research Python unit tests
  6. CBRC Gaussian+temporal randomized falsification chain
  7. CBRC synthetic pilot

Optional real campaign:
  Set MAVEB_CAMPAIGN=/absolute/path/campaign.json
  Set MAVEB_WORK_COST=/absolute/path/frozen-work-cost.json if your campaign manifest
  or local workflow requires it.

The real campaign additionally requires the scene archives/sidecars referenced by
the frozen manifest. Missing real evidence is reported as pending; it is never
substituted with synthetic data.
EOF
}

if [[ "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi
if [[ $# -ne 0 ]]; then
  usage >&2
  exit 2
fi

echo "==> [1/7] whitespace"
git diff --check HEAD^

echo "==> [2/7] CI build and tests"
cmake --preset ci
cmake --build --preset ci --parallel
ctest --preset ci

echo "==> [3/7] sanitizer build and tests"
cmake --preset sanitizer
cmake --build --preset sanitizer --parallel
ctest --test-dir build/sanitizer --output-on-failure

echo "==> [4/7] Python test suites"
python3 -m unittest discover -s benchmarks/tests -p 'test_*.py'
python3 -m unittest discover -s research/tests -p 'test_*.py'

echo "==> [5/7] randomized CBRC falsification"
python3 research/experiments/cbrc_gaussian_temporal_chain.py \
  --seed 20260920 \
  --trials 100000

echo "==> [6/7] synthetic CBRC pilot"
mkdir -p build/research-final
python3 research/experiments/cbrc_synthetic_benchmark.py \
  --out build/research-final/cbrc-synthetic-pilot.jsonl \
  --seed 20260920 \
  --repeats 1 \
  --pilot

echo "==> [7/7] real campaign"
if [[ -n "${MAVEB_CAMPAIGN:-}" ]]; then
  [[ -f "$MAVEB_CAMPAIGN" ]] || {
    echo "MAVEB_CAMPAIGN does not exist: $MAVEB_CAMPAIGN" >&2
    exit 3
  }
  if [[ -n "${MAVEB_WORK_COST:-}" && ! -f "$MAVEB_WORK_COST" ]]; then
    echo "MAVEB_WORK_COST does not exist: $MAVEB_WORK_COST" >&2
    exit 3
  fi

  python3 benchmarks/scripts/cbrc_campaign.py \
    --campaign "$MAVEB_CAMPAIGN" \
    --oracle build/ci/tools/maveb-cbrc-gaussian-oracle/maveb-cbrc-gaussian-oracle \
    --revision-tool build/ci/tools/maveb-cbrc-revision/maveb-cbrc-revision \
    --git-sha "$(git rev-parse HEAD)" \
    --output-dir build/research-final/real-campaign
else
  echo "SKIP: no MAVEB_CAMPAIGN supplied; real-scene evidence remains pending."
fi

echo "==> MAVEB verification complete"
