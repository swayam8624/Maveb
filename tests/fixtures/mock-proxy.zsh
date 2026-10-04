#!/bin/zsh
set -euo pipefail
if [[ ${1:-} == --version ]]; then
  print "aether-proxy 0.1.0 (Open3D 0.19.0)"
  exit 0
fi
points=${1:?missing points3D input}
[[ -f ${points} ]]
shift
output=
report=
while (( $# > 1 )); do
  case $1 in
    --output) output=$2 ;;
    --report) report=$2 ;;
  esac
  shift
done
[[ -n ${output} && -n ${report} ]]
mkdir -p ${output:h} ${report:h}
print 'ply' > ${output}
print '{"schemaVersion":1,"tool":{"name":"aether-proxy","version":"0.1.0","open3d":"0.19.0"},"output":{"vertices":3,"triangles":1}}' > ${report}
