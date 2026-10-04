#!/bin/zsh
set -euo pipefail
reconstruct=${1:?missing reconstruct executable}
dataset=${2:?missing dataset}
output=${3:?missing output directory}
colmap=${4:?missing COLMAP mock}
brush=${5:?missing Brush mock}
proxy=${6:?missing proxy mock}
before=$(/usr/bin/shasum -a 256 ${output}/resume-key.txt)
set +e
${reconstruct} ${dataset} --output ${output} --colmap ${colmap} --brush ${brush} \
  --proxy ${proxy} --seed 42 --steps 11 --checkpoint-every 5 --json \
  >/dev/null 2>${output}/resume-mismatch.stderr
exit_code=$?
set -e
[[ ${exit_code} == 3 ]]
after=$(/usr/bin/shasum -a 256 ${output}/resume-key.txt)
[[ ${before} == ${after} ]]
[[ ! -e ${output}/exports/checkpoint_11.ply ]]
/usr/bin/grep -q 'choose a new job directory' ${output}/resume-mismatch.stderr
/usr/bin/grep -q '"status":"complete"' ${output}/job.json
