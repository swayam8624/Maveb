#!/bin/zsh
set -euo pipefail

root=${0:A:h:h}
export MAVEB_ROOT=${MAVEB_ROOT:-${root}}
export MAVEB_DATA=${MAVEB_DATA:-${HOME}/Datasets/MavebBench}
export PATH="${MAVEB_ROOT}/.aether-deps/bin:${PATH}"

if [[ -n ${MAVEB_PYTHON:-} ]]; then
    python=${MAVEB_PYTHON}
elif [[ -x ${MAVEB_ROOT}/.aether-deps/proxy-venv/bin/python ]]; then
    python=${MAVEB_ROOT}/.aether-deps/proxy-venv/bin/python
else
    python=$(command -v python3)
fi

exec "${python}" "${MAVEB_ROOT}/benchmarks/scripts/mavebbench.py" "$@"
