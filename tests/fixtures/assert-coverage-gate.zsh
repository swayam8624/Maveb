#!/bin/zsh
set -euo pipefail
reconstruct=${1:?missing reconstruct executable}
dataset=${2:?missing dataset}
output=${3:?missing output directory}
colmap=${4:?missing COLMAP mock}
brush=${5:?missing Brush mock}
proxy=${6:?missing proxy mock}
rm -rf ${output}
set +e
${reconstruct} ${dataset} --output ${output} --colmap ${colmap} --brush ${brush} --proxy ${proxy} \
  --seed 42 --steps 10 --json >/dev/null 2>${output}.stderr
exit_code=$?
set -e
[[ ${exit_code} == 5 ]]
[[ -f ${output}/sparse-selection.json ]]
[[ ! -e ${output}/pose-coverage-validation.complete ]]
[[ ! -e ${output}/exports/base-gaussians.ply ]]
[[ ! -e ${output}/proxy/proxy.ply ]]
/usr/bin/grep -q '"selectedModel":null' ${output}/sparse-selection.json
/usr/bin/grep -q '"passed":false' ${output}/sparse-selection.json
/usr/bin/grep -q '"status":"coverage-failed"' ${output}/job.json
