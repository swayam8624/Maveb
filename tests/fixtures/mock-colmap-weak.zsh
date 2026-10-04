#!/bin/zsh
set -euo pipefail
script_dir=${0:a:h}
if [[ ${1:-} == model_converter ]]; then
  shift
  output=
  while (( $# > 1 )); do
    if [[ $1 == --output_path ]]; then
      output=$2
      break
    fi
    shift
  done
  [[ -n ${output} ]]
  mkdir -p ${output}
  : > ${output}/cameras.txt
  : > ${output}/points3D.txt
  print '1 1 0 0 0 0 0 0 1 001.jpg' > ${output}/images.txt
  print '' >> ${output}/images.txt
  print '2 1 0 0 0 0 0 0 1 002.jpg' >> ${output}/images.txt
  print '' >> ${output}/images.txt
  exit 0
fi
exec ${script_dir}/mock-colmap.zsh "$@"
