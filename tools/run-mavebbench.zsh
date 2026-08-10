#!/bin/zsh
set -euo pipefail

root=${0:A:h:h}
export MAVEB_ROOT=${MAVEB_ROOT:-${root}}
export MAVEB_DATA=${MAVEB_DATA:-${HOME}/Datasets/MavebBench}
export PATH="${MAVEB_ROOT}/.aether-deps/bin:${PATH}"
exec python3 ${MAVEB_ROOT}/benchmarks/scripts/mavebbench.py "$@"
