#!/bin/zsh
set -euo pipefail

root=${0:A:h:h}
deps=${AETHER_DEPS_ROOT:-${root}/.aether-deps}
sources=${deps}/src
bin=${deps}/bin
mkdir -p ${sources} ${bin}
export PATH="${bin}:${PATH}"

brush_commit=3edecbb2fe79d3e2c87eeab85b15e0b1dd10d486
brush_source=${sources}/brush
if [[ ! -d ${brush_source}/.git ]]; then
  git clone --filter=blob:none https://github.com/ArthurBrussee/brush.git ${brush_source}
fi
git -C ${brush_source} fetch --depth 1 origin ${brush_commit}
git -C ${brush_source} checkout --detach ${brush_commit}
[[ $(git -C ${brush_source} rev-parse HEAD) == ${brush_commit} ]]
cargo build --locked --release --manifest-path ${brush_source}/Cargo.toml \
  --package brush-app --bin brush_app
ln -sfn ${brush_source}/target/release/brush_app ${bin}/brush

if ! command -v uv >/dev/null 2>&1; then
  print -u2 "AETHER proxy setup requires uv; install it without elevated privileges, then rerun."
  exit 5
fi
if ! command -v python3.12 >/dev/null 2>&1; then
  print -u2 "AETHER proxy setup requires Python 3.12 for the pinned Open3D wheel."
  exit 5
fi
UV_PROJECT_ENVIRONMENT=${deps}/proxy-venv uv sync \
  --project ${root}/tools/aether-proxy --python $(command -v python3.12) --locked --no-dev
ln -sfn ${deps}/proxy-venv/bin/aether-proxy ${bin}/aether-proxy

colmap_commit=0b31f98133b470eae62811b557dc2bcff1e4f9a5
local_colmap=${deps}/colmap-install/bin/colmap

if [[ -x ${local_colmap} ]]; then
  ln -sfn ${local_colmap} ${bin}/colmap
elif command -v colmap >/dev/null 2>&1; then
  colmap_version=$(colmap 2>&1 | grep -E "COLMAP [0-9]+\.[0-9]+" | head -n 1 || true)
  if [[ ${colmap_version} != *3.13.0* ]]; then
    print -u2 "AETHER requires COLMAP 3.13.0; found: ${colmap_version}"
    exit 3
  fi
  if [[ $(command -v colmap) != ${bin}/colmap ]]; then
    ln -sfn $(command -v colmap) ${bin}/colmap
  fi
else
  colmap_source=${sources}/colmap
  if [[ ! -d ${colmap_source}/.git ]]; then
    git clone --filter=blob:none https://github.com/colmap/colmap.git ${colmap_source}
  fi
  git -C ${colmap_source} fetch --depth 1 origin ${colmap_commit}
  git -C ${colmap_source} checkout --detach ${colmap_commit}
  [[ $(git -C ${colmap_source} rev-parse HEAD) == ${colmap_commit} ]]

  if [[ ${AETHER_BUILD_COLMAP:-0} == 1 ]]; then
    ${root}/tools/build-colmap-macos.zsh
  else
    print -u2 "Pinned COLMAP source is ready at ${colmap_source}."
    print -u2 "Run tools/build-colmap-macos.zsh after installing the documented native dependencies,"
    print -u2 "or rerun with AETHER_BUILD_COLMAP=1 to configure/build/install automatically."
    exit 4
  fi
fi

${bin}/brush --version
${bin}/colmap 2>&1 | head -n 2
${bin}/aether-proxy --version
print "AETHER reconstruction tools are ready in ${bin}"
