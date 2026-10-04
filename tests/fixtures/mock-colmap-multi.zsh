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
    mkdir -p ${output}/0 ${output}/1
    ;;
  model_converter)
    input=$(value_after --input_path $@)
    output=$(value_after --output_path $@)
    mkdir -p ${output}
    cat > ${output}/images.txt <<'EOF'
# Image list
1 0.9987502604 0 0.0499791693 0 1 0 0 1 ipad/001.jpg
0 0 1 1 0 2 2 0 3
2 1 0 0 0 0 0 0 1 sony/001.jpg
0 0 1 1 0 2 2 0 3
3 0.9987502604 0 -0.0499791693 0 -1 0 0 1 sony/002.jpg
0 0 1 1 0 2 2 0 3
EOF
    : > ${output}/cameras.txt
    : > ${output}/points3D.txt
    if [[ ${input:t} == 0 ]]; then
      print '1 0 0 3 128 128 128 0.1 99 0' >> ${output}/points3D.txt
    else
      for (( point=1; point<=48; ++point )); do
        print "${point} 0 0 $((point + 2)) 128 128 128 0.1 1 ${point} 2 ${point} 3 ${point}" >> ${output}/points3D.txt
      done
    fi
    ;;
  image_undistorter)
    input=$(value_after --input_path $@)
    [[ ${input:t} == 1 ]]
    output=$(value_after --output_path $@)
    mkdir -p ${output}/sparse
    ;;
  *)
    print -u2 "Unexpected mock COLMAP command: ${command}"
    exit 9
    ;;
esac
