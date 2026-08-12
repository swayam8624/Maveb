#!/bin/zsh
set -euo pipefail
if [[ ${1:-} == --version ]]; then
  print "COLMAP 3.13.0"
  exit 0
fi
command=${1:?missing COLMAP command}
shift
value_after() {
  local key=$1
  shift
  while (( $# > 1 )); do
    if [[ $1 == ${key} ]]; then
      print $2
      return
    fi
    shift
  done
  return 1
}
case ${command} in
  feature_extractor)
    database=$(value_after --database_path $@)
    mkdir -p ${database:h}
    : > ${database}
    ;;
  exhaustive_matcher|sequential_matcher)
    [[ -f $(value_after --database_path $@) ]]
    ;;
  mapper)
    output=$(value_after --output_path $@)
    mkdir -p ${output}/0
    ;;
  model_converter)
    output=$(value_after --output_path $@)
    mkdir -p ${output}
    cat > ${output}/images.txt <<'EOF'
# Image list
1 0.9987502604 0 0.0499791693 0 1 0 0 1 001.jpg
0 0 1 1 0 2 2 0 3
2 1 0 0 0 0 0 0 1 002.jpg
0 0 1 1 0 2 2 0 3
3 0.9987502604 0 -0.0499791693 0 -1 0 0 1 003.jpg
0 0 1 1 0 2 2 0 3
EOF
    : > ${output}/cameras.txt
    : > ${output}/points3D.txt
    for point in {1..24}; do
      print "${point} 0 0 $((point + 2)) 128 128 128 0.1 1 ${point} 2 ${point} 3 ${point}" >> ${output}/points3D.txt
    done
    ;;
  image_undistorter)
    output=$(value_after --output_path $@)
    mkdir -p ${output}/sparse
    ;;
  *)
    print -u2 "Unexpected mock COLMAP command: ${command}"
    exit 9
    ;;
esac
