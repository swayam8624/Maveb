# Incremental sparse TSDF meshing evidence — E2

Date: 2026-08-13

This tranche replaces allocated-span remeshing with deterministic dirty-block patches. It is a
production scheduling and correctness boundary, not yet GPU-resident Marching Cubes or a live-rate
performance claim.

## Implemented proof

- CPU and Metal fusion expose the same immutable sparse snapshot schema and completed generation.
- A patch owns only cells whose minimum grid corner belongs to its block.
- Positive topology and symmetric gradient halos give bit-exact positions and normals at shared
  patch boundaries.
- Dirty blocks invalidate the seven negative owner neighbours that can reference changed samples.
- Patch updates replace or explicitly remove cached geometry.
- Stale generations, malformed snapshots, out-of-range dirtiness, patch exhaustion, and voxel
  exhaustion fail without partially changing the cache.
- Metal-produced snapshots drive the same mesher and match the CPU full extractor's triangle count.

## Fixture evidence

The translated/yaw-rotated plane produces 106 dirty blocks, 120 patch updates, 30 resident surface
patches, and 1,680 triangles. Full extraction also produces 1,680 triangles. Shared boundary
positions and normals are bit-exact. Raw evidence is committed at
`benchmarks/evidence/r5-incremental-meshing-m2-pro-2026-08-13.json`.

## Verification

```text
cmake --build --preset debug -j 8
ctest --preset debug --output-on-failure
Result: build passed; 33/33 tests passed

MTL_DEBUG_LAYER=1 MTL_SHADER_VALIDATION=1 \
  build/debug/tests/AetherSparseMetalTsdfTests \
  --json-output build/debug/test-artifacts/r5-sparse-metal-tsdf.json
Result: passed with Metal API Validation and Metal GPU Validation enabled

cmake --preset ci
cmake --build --preset ci -j 8
ctest --preset ci --output-on-failure
Result: warnings-as-errors build passed; 26/26 tests passed

cmake --preset sanitizer
cmake --build --preset sanitizer -j 8
ctest --test-dir build/sanitizer --output-on-failure
Result: build passed; 26/26 tests passed under the sanitizer configuration

/opt/homebrew/opt/llvm/bin/clang-format --dry-run --Werror <changed C++ files>
Result: passed with installed clang-format 22

/opt/homebrew/opt/llvm/bin/clang-tidy -p build/ci --warnings-as-errors='*' \
  engine/reconstruction/src/DenseTsdfVolume.cpp \
  engine/reconstruction/src/IncrementalSparseTsdfMesher.cpp \
  engine/reconstruction/src/SparseTsdfVolume.cpp \
  tests/SparseTsdfTests.cpp tests/SparseMetalTsdfTests.cpp \
  --extra-arg=-isysroot --extra-arg="$(xcrun --sdk macosx --show-sdk-path)"
Result: passed; dependency and system warnings were suppressed by clang-tidy

../Maveb/.aether-deps/proxy-venv/bin/python \
  -m unittest discover -s benchmarks/tests -p 'test_*.py'
Result: 17/17 passed

cmp build/debug/test-artifacts/r5-incremental-meshing.json \
  benchmarks/evidence/r5-incremental-meshing-m2-pro-2026-08-13.json
Result: passed; generated and committed reports are byte-identical

build/debug/apps/AetherStudio/AetherStudio.app/Contents/MacOS/AetherStudio
Result: launched successfully for a five-second smoke and was then terminated manually

git diff --check
Result: passed
```

The local LLVM toolchain is version 22; hosted CI uses the repository-pinned LLVM 18 tools.

## Remaining R5 work

Patch extraction still runs on the CPU and the current Metal snapshot copies all resident blocks.
Selective readback, GPU-resident Marching Cubes, asynchronous scheduling, persistence/eviction,
real-capture evidence, and throughput/soak gates remain open.
