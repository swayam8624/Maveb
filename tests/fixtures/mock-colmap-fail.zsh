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
    print -u2 "fixture matching failure"
    exit 7
    ;;
  *)
    print -u2 "Unexpected command after fixture failure: ${command}"
    exit 9
    ;;
esac
