#!/bin/zsh
set -euo pipefail
reconstruct=${1:?missing reconstruct executable}
dataset=${2:?missing dataset}
output=${3:?missing output directory}
colmap=${4:?missing COLMAP mock}
brush=${5:?missing Brush mock}
proxy=${6:?missing proxy mock}
cp ${output}/exports/checkpoint_10.ply ${output}/exports/checkpoint_05.ply
print 'incomplete checkpoint' > ${output}/exports/checkpoint_08.ply
rm ${output}/exports/checkpoint_10.ply ${output}/exports/base-gaussians.ply \
  ${output}/brush-training.complete
${reconstruct} ${dataset} --output ${output} --colmap ${colmap} --brush ${brush} \
  --proxy ${proxy} --seed 42 --steps 10 --checkpoint-every 5 --json >/dev/null
[[ -f ${output}/dense/init.ply ]]
[[ -f ${output}/exports/checkpoint_10.ply ]]
[[ -f ${output}/exports/base-gaussians.ply ]]
/usr/bin/grep -q '"checkpointRecovery":{"iteration":5' ${output}/job.json
/usr/bin/grep -q '"rejectedNewerCheckpoints":1' ${output}/job.json
/usr/bin/grep -q '"optimizerStateRestored":false' ${output}/job.json
