#!/bin/zsh
set -euo pipefail
reconstruct=${1:?missing reconstruct executable}
dataset=${2:?missing dataset}
fixture_root=${3:?missing fixture root}
multi_dataset=${4:?missing multi-camera dataset}
camera_groups=${5:?missing camera-group manifest}
mkdir -p ${fixture_root}
image_list=${fixture_root}/selected-images.txt
preprocessing=${fixture_root}/keyframes.json
print '001.jpg\n002.jpg\n003.jpg' > ${image_list}
print '{"schemaVersion":1,"fixture":true}' > ${preprocessing}
output=$(${reconstruct} ${dataset} --output ${fixture_root}/video-job --input-kind video \
  --image-list ${image_list} --preprocessing-manifest ${preprocessing} --dry-run --json)
print ${output} | /usr/bin/grep -q '"matcher":"sequential"'
print ${output} | /usr/bin/grep -q 'sequential_matcher'
print ${output} | /usr/bin/grep -q -- '--SequentialMatching.overlap 10'
print ${output} | /usr/bin/grep -q -- '--image_list_path'

set +e
${reconstruct} ${dataset} --output ${fixture_root}/invalid-multi --input-kind multi-camera \
  --dry-run --json >/dev/null 2>${fixture_root}/invalid-multi.stderr
exit_code=$?
set -e
[[ ${exit_code} == 2 ]]
/usr/bin/grep -q 'requires --camera-groups' ${fixture_root}/invalid-multi.stderr

multi_output=$(${reconstruct} ${multi_dataset} --output ${fixture_root}/multi-job \
  --input-kind multi-camera --camera-groups ${camera_groups} --dry-run --json)
print ${multi_output} | /usr/bin/grep -q '"cameraGrouping":"per-folder"'
print ${multi_output} | /usr/bin/grep -q -- '--ImageReader.single_camera_per_folder 1'
