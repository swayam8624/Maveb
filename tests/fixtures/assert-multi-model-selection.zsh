#!/bin/zsh
set -euo pipefail
reconstruct=${1:?missing reconstruct executable}
dataset=${2:?missing dataset}
output=${3:?missing output directory}
colmap=${4:?missing COLMAP mock}
brush=${5:?missing Brush mock}
proxy=${6:?missing proxy mock}
camera_groups=${7:?missing camera-group manifest}
rm -rf ${output}
${reconstruct} ${dataset} --output ${output} --colmap ${colmap} --brush ${brush} \
  --proxy ${proxy} --input-kind multi-camera --camera-groups ${camera_groups} \
  --seed 42 --steps 10 --checkpoint-every 5 --json >/dev/null
[[ -f ${output}/sparse/models/0-text/images.txt ]]
[[ -f ${output}/sparse/models/1-text/images.txt ]]
[[ -f ${output}/sparse/selected-text/images.txt ]]
/usr/bin/grep -q '"selectedModel":"1"' ${output}/sparse-selection.json
/usr/bin/grep -q 'Model validation failed' ${output}/sparse-selection.json
/usr/bin/grep -q '"selectedModel":"1"' ${output}/job.json
/usr/bin/grep -q '"id":"sony-a7v-35mm"' ${output}/job.json
/usr/bin/grep -q '"mode":"per-folder"' ${output}/job.json
/usr/bin/grep -q '/sparse/1' ${output}/job.json
/usr/bin/grep -q '"trackedPoints":48' ${output}/pose-coverage.json
