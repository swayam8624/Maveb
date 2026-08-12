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
${reconstruct} ${dataset} --output ${output} --colmap ${colmap} --brush ${brush} \
  --proxy ${proxy} --seed 42 --steps 10 --checkpoint-every 5 --json \
  >/dev/null 2>${output}.stderr
exit_code=$?
set -e
[[ ${exit_code} == 4 ]]
/usr/bin/grep -q '"status":"failed"' ${output}/job.json
/usr/bin/grep -q '"failedStage":"feature-matching"' ${output}/job.json
[[ ! -e ${output}/sparse-selection.json ]]
[[ ! -e ${output}/proxy/proxy.ply ]]
