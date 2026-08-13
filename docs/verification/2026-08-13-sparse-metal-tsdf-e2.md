# Sparse Metal TSDF fusion evidence — E2

Date: 2026-08-13

This record establishes fixture-level CPU/GPU agreement for the first Metal 3 block-sparse TSDF
fusion backend. It does not claim real-capture accuracy, asynchronous live reconstruction,
incremental meshing, or production throughput.

## Implemented proof

- CPU and Metal fusion consume one deterministic, validated candidate-block contract.
- The GPU classifies candidate voxels before resident block assignment and performs calibrated
  projection, depth/confidence rejection, signed-distance fusion, color accumulation, weight
  saturation, and observation counting.
- Stable host slots preserve deterministic block identity; immutable snapshots expose only a
  completed generation.
- Fusion occurs in private scratch storage before publication to the resident volume.
- Frame-pixel, resident-block, resident-byte, and scratch-byte limits reject hostile work without
  advancing resident blocks or generation.
- Shared C++/MSL structures have compile-time size, alignment, and offset checks, and the shader is
  compiled offline into the Studio metallib.

## Deterministic measurements

On the Apple M2 Pro, two independent GPU volumes produced identical first-generation snapshots.
After a repeated frame reached configured weight saturation, the Metal volume held 92 four-cubed
blocks and 3,253 observed voxels. All 4,820 resident voxel records compared against the CPU sparse
reference within the declared `2e-5` floating-point tolerance; zero mismatches were found. The raw
report is committed at `benchmarks/evidence/r5-sparse-metal-m2-pro-2026-08-13.json`.

## Verification commands and actual results

```text
cmake --build --preset debug -j 8
ctest --preset debug --output-on-failure
Result: build passed, including offline tsdf.metal compilation; 32/32 tests passed

MTL_DEBUG_LAYER=1 MTL_SHADER_VALIDATION=1 \
  build/debug/tests/AetherSparseMetalTsdfTests \
  --json-output build/debug/test-artifacts/r5-sparse-metal-tsdf.json
Result: passed with Metal API Validation and Metal GPU Validation enabled

cmp build/debug/test-artifacts/r5-sparse-metal-tsdf.json \
  benchmarks/evidence/r5-sparse-metal-m2-pro-2026-08-13.json
Result: passed; generated and committed reports are byte-identical

cmake --preset ci
cmake --build --preset ci -j 8
ctest --preset ci --output-on-failure
Result: build passed with warnings as errors; 25/25 tests passed

cmake --preset sanitizer
cmake --build --preset sanitizer -j 8
ctest --test-dir build/sanitizer --output-on-failure
Result: build passed; 25/25 tests passed under the sanitizer configuration

/opt/homebrew/opt/llvm/bin/clang-format --dry-run --Werror <changed C++ and header files>
Result: passed with installed clang-format 22

/opt/homebrew/opt/llvm/bin/clang-tidy -p build/ci --warnings-as-errors='*' \
  engine/metal/src/ShaderABI.cpp engine/metal/src/SparseMetalTsdfVolume.cpp \
  engine/reconstruction/src/SparseTsdfVolume.cpp tests/SparseMetalTsdfTests.cpp \
  --extra-arg=-isysroot --extra-arg="$(xcrun --sdk macosx --show-sdk-path)"
Result: passed; dependency and system warnings were suppressed by clang-tidy

../Maveb/.aether-deps/proxy-venv/bin/python \
  -m unittest discover -s benchmarks/tests -p 'test_*.py'
Result: 17/17 passed

build/debug/apps/AetherStudio/AetherStudio.app/Contents/MacOS/AetherStudio
Result: launched successfully for a five-second smoke and was then terminated manually

git diff --check
Result: passed
```

The local LLVM toolchain is version 22; hosted CI uses the repository-pinned LLVM 18 formatter and
static analyzer. The GPU test is registered only when the offline shader target exists. Ordinary
Apple hosted builds still compile the Metal backend and test binary for warnings/static analysis
without treating a runner GPU as evidence.

## Remaining R5 work

Metal fusion is currently synchronous and fixture-driven. R5 remains open for asynchronous
capture/depth/fusion scheduling, halo-consistent dirty-block meshing, memory-pressure persistence
and eviction, real-capture CPU/GPU agreement, checkpoint recovery, and the stated 30-minute and
throughput gates.
