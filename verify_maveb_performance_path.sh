#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON="${MAVEB_PYTHON:-$ROOT/.venv-maveb/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="${MAVEB_PYTHON:-python3}"
fi

echo "==> Syntax checking optimized runners"
"$PYTHON" -m py_compile   benchmarks/scripts/cbrc_campaign.py   benchmarks/scripts/cbrc_prepare_broad_worlds.py
bash -n run_broad_benchmark_campaign.sh
bash -n run_broad_benchmark_fast.sh

echo "==> Configuring Release research build"
cmake --preset research

echo "==> Building optimized research tools"
cmake --build --preset research --parallel --target   maveb-cbrc-revision   maveb-cbrc-gaussian-oracle   maveb-cbrc-work-bench   maveb-seed-trained-3dgs-world   maveb-seed-world

ORACLE="$ROOT/build/research/tools/maveb-cbrc-gaussian-oracle/maveb-cbrc-gaussian-oracle"
BEFORE="$ROOT/tests/fixtures/cbrc-gaussian-before.ply"
AFTER="$ROOT/tests/fixtures/cbrc-gaussian-after.ply"

echo "==> CPU oracle fixture"
"$ORACLE"   --before "$BEFORE"   --after "$AFTER"   --detect-changed   --backend cpu   --width 64 --height 64   --focal-x 70 --focal-y 70   --center-x 32 --center-y 32   --epsilon 1.0 >/tmp/maveb-oracle-cpu.json

if [[ "$(uname -s)" == "Darwin" ]]; then
  echo "==> Metal oracle parity against CPU"
  "$ORACLE"     --before "$BEFORE"     --after "$AFTER"     --detect-changed     --backend metal     --verify-metal-parity     --width 64 --height 64     --focal-x 70 --focal-y 70     --center-x 32 --center-y 32     --epsilon 1.0 >/tmp/maveb-oracle-metal.json

  echo "==> CPU fixture timing"
  /usr/bin/time -p "$ORACLE"     --before "$BEFORE" --after "$AFTER" --detect-changed --backend cpu     --width 320 --height 180 --focal-x 260 --focal-y 260     --center-x 160 --center-y 90 --epsilon 1.0 >/dev/null

  echo "==> Metal fixture timing"
  /usr/bin/time -p "$ORACLE"     --before "$BEFORE" --after "$AFTER" --detect-changed --backend metal     --width 320 --height 180 --focal-x 260 --focal-y 260     --center-x 160 --center-y 90 --epsilon 1.0 >/dev/null
fi

echo
echo "MAVEB optimized execution path validated."
echo "Fast iteration:        bash run_broad_benchmark_fast.sh"
echo "Publication campaign:  bash run_broad_benchmark_campaign.sh"
echo "GPU publication trial: MAVEB_ORACLE_BACKEND=auto bash run_broad_benchmark_campaign.sh"
