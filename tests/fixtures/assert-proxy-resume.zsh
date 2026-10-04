#!/bin/zsh
set -euo pipefail
reconstruct=${1:?missing reconstruct executable}
dataset=${2:?missing dataset}
output=${3:?missing output directory}
colmap=${4:?missing COLMAP mock}
brush=${5:?missing Brush mock}
proxy=${6:?missing proxy mock}
rm ${output}/proxy/proxy.json
${reconstruct} ${dataset} --output ${output} --colmap ${colmap} --brush ${brush} \
  --proxy ${proxy} --seed 42 --steps 10 --checkpoint-every 5 --json >/dev/null
[[ -f ${output}/proxy/proxy.ply ]]
[[ -f ${output}/proxy/proxy.json ]]
[[ -f ${output}/proxy-generation.complete ]]
