#!/bin/zsh
set -euo pipefail
reconstruct=${1:?missing reconstruct executable}
dataset=${2:?missing dataset}
output=${3:?missing output directory}
colmap=${4:?missing COLMAP mock}
brush=${5:?missing Brush mock}
proxy=${6:?missing proxy mock}
set +e
${reconstruct} ${dataset} --output ${output} --colmap ${colmap} --brush ${brush} \
  --proxy ${proxy} --input-kind video --seed 42 --steps 10 --checkpoint-every 5 --json \
  >/dev/null 2>${output}/strategy-mismatch.stderr
exit_code=$?
set -e
[[ ${exit_code} == 3 ]]
/usr/bin/grep -q 'choose a new job directory' ${output}/strategy-mismatch.stderr
/usr/bin/grep -q '"status":"complete"' ${output}/job.json
