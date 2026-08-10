#!/bin/zsh
set -euo pipefail

if [[ ${OSTYPE:-} != darwin* ]]; then
  print -u2 "This helper is for the Apple-silicon/macOS reconstruction path."
  exit 2
fi

root=${0:A:h:h}
deps=${AETHER_DEPS_ROOT:-${root}/.aether-deps}
source_dir=${deps}/src/colmap
build_dir=${source_dir}/build-aether
install_dir=${deps}/colmap-install
bin=${deps}/bin
expected_commit=0b31f98133b470eae62811b557dc2bcff1e4f9a5

for tool in cmake ninja; do
  if ! command -v ${tool} >/dev/null 2>&1; then
    print -u2 "Missing ${tool}. Install the documented native COLMAP prerequisites and rerun."
    exit 3
  fi
done

if [[ ! -d ${source_dir}/.git ]]; then
  mkdir -p ${deps}/src
  git clone --filter=blob:none https://github.com/colmap/colmap.git ${source_dir}
fi

git -C ${source_dir} fetch --depth 1 origin ${expected_commit}
git -C ${source_dir} checkout --detach ${expected_commit}
[[ $(git -C ${source_dir} rev-parse HEAD) == ${expected_commit} ]]

cmake -S ${source_dir} -B ${build_dir} -GNinja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX=${install_dir} \
  -DGUI_ENABLED=OFF \
  -DCUDA_ENABLED=OFF \
  -DTESTS_ENABLED=OFF

cmake --build ${build_dir} --parallel
cmake --install ${build_dir}

mkdir -p ${bin}
ln -sfn ${install_dir}/bin/colmap ${bin}/colmap
${bin}/colmap 2>&1 | head -n 2
print "Pinned COLMAP installed at ${bin}/colmap"
