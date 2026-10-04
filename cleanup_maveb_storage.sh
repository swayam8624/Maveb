#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON="${MAVEB_PYTHON:-$ROOT/.venv-maveb/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="${MAVEB_PYTHON:-python3}"
fi

MODE="${1:-report}"
case "$MODE" in
  report|--report)
    exec "$PYTHON" benchmarks/scripts/cbrc_storage_doctor.py       --repo "$ROOT"       --minimum-free-gib 0
    ;;
  safe|--safe|--cleanup-safe)
    exec "$PYTHON" benchmarks/scripts/cbrc_storage_doctor.py       --repo "$ROOT"       --cleanup-safe       --minimum-free-gib 0
    ;;
  *)
    echo "Usage:" >&2
    echo "  bash cleanup_maveb_storage.sh          # report only" >&2
    echo "  bash cleanup_maveb_storage.sh --safe   # verified safe cleanup" >&2
    exit 2
    ;;
esac
