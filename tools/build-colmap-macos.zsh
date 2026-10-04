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

for tool in cmake ninja brew; do
  if ! command -v ${tool} >/dev/null 2>&1; then
    print -u2 "Missing ${tool}. Install the documented native COLMAP prerequisites and rerun."
    exit 3
  fi
done

homebrew_prefix=$(brew --prefix)
boost_prefix=$(brew --prefix boost)
glog_prefix=$(brew --prefix glog)

# COLMAP's pinned 3.13.0 source predates the current glog export-header
# consumption requirement. Homebrew's modern glog requires consumers to
# compile with GLOG_USE_GLOG_EXPORT so that glog/export.h defines GLOG_EXPORT.
#
# Also isolate the native build from Conda/Anaconda CMake and header search
# paths. A user with an activated base Conda environment can otherwise end up
# with Homebrew glog/Ceres but Conda Boost, producing an ABI/header mixture.
typeset -a sanitized_env
sanitized_env=(
  env
  -u CONDA_PREFIX
  -u CONDA_DEFAULT_ENV
  -u CONDA_PROMPT_MODIFIER
  -u CMAKE_PREFIX_PATH
  -u CPATH
  -u CPLUS_INCLUDE_PATH
  -u C_INCLUDE_PATH
  -u LIBRARY_PATH
  -u DYLD_LIBRARY_PATH
  -u PKG_CONFIG_PATH
  -u CPPFLAGS
  -u CXXFLAGS
  -u CFLAGS
  -u LDFLAGS
)

if [[ ! -d ${source_dir}/.git ]]; then
  mkdir -p ${deps}/src
  git clone --filter=blob:none https://github.com/colmap/colmap.git ${source_dir}
fi

git -C ${source_dir} fetch --depth 1 origin ${expected_commit}
git -C ${source_dir} checkout --detach ${expected_commit}
[[ $(git -C ${source_dir} rev-parse HEAD) == ${expected_commit} ]]

# Failed/previous configurations may cache a Conda Boost path, so always
# configure this pinned dependency from a clean build directory.
rm -rf ${build_dir}
mkdir -p ${build_dir}

${sanitized_env[@]} cmake -S ${source_dir} -B ${build_dir} -GNinja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX=${install_dir} \
  -DCMAKE_PREFIX_PATH="${homebrew_prefix}" \
  -DBOOST_ROOT="${boost_prefix}" \
  -DBoost_NO_SYSTEM_PATHS=ON \
  -DCMAKE_CXX_FLAGS="-DGLOG_USE_GLOG_EXPORT" \
  -DGUI_ENABLED=OFF \
  -DCUDA_ENABLED=OFF \
  -DTESTS_ENABLED=OFF

if grep -Eiq '/(anaconda[^/]*|miniconda[^/]*|conda[^/]*)/' ${build_dir}/CMakeCache.txt; then
  print -u2 "Refusing COLMAP build: Conda/Anaconda paths leaked into CMakeCache.txt."
  print -u2 "Deactivate Conda and rerun tools/build-colmap-macos.zsh."
  exit 5
fi

if ! grep -Fq "${glog_prefix}" ${build_dir}/CMakeCache.txt && \
   ! grep -Fq "${homebrew_prefix}" ${build_dir}/CMakeCache.txt; then
  print -u2 "COLMAP configure did not resolve the expected Homebrew dependency prefix."
  exit 5
fi

${sanitized_env[@]} cmake --build ${build_dir} --parallel
${sanitized_env[@]} cmake --install ${build_dir}

mkdir -p ${bin}
ln -sfn ${install_dir}/bin/colmap ${bin}/colmap
${bin}/colmap 2>&1 | head -n 2
print "Pinned COLMAP installed at ${bin}/colmap"
