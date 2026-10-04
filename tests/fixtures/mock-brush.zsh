#!/bin/zsh
set -euo pipefail
if [[ ${1:-} == --version ]]; then
  print "brush-app 0.3.0"
  exit 0
fi
shift
export_path=
export_name=
total_steps=
while (( $# > 1 )); do
  case $1 in
    --export-path) export_path=$2 ;;
    --export-name) export_name=$2 ;;
    --total-steps) total_steps=$2 ;;
  esac
  shift
done
[[ -n ${export_path} && -n ${export_name} && -n ${total_steps} ]]
mkdir -p ${export_path}
printf -v padded "%0${#total_steps}d" ${total_steps}
export_name=${export_name//\{iter\}/${padded}}
cp ${0:a:h}/gaussian-minimal.ply ${export_path}/${export_name}
