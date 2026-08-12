# Native static GLB export — E2 verification

Date: 2026-08-12

Scope: deterministic bounded GLB authoring from Maveb `MeshAsset`, loader support for `COLOR_0`,
and recorded RGB-D oracle export through `aether-fuse`.

## Evidence boundary

This is E2 fixture evidence. It proves deterministic encoding, semantic validation, hostile-input
rejection, atomic replacement, static instance and PBR round-trips, and a CLI oracle smoke test. It
does not prove real Sony/iPad alignment, texture reconstruction, geometric accuracy on a new
capture, or USDZ ingestion.

## Commands and results

Warnings-as-errors CPU build and the complete registered test suite:

```bash
cmake --build --preset ci --parallel 8
ctest --preset ci --output-on-failure
```

Result: build succeeded; 11/11 tests passed. `AetherTests` covers byte-for-byte determinism,
canonical GLB validation, load/export round-trip, embedded image and sampler preservation, PBR and
UV-transform preservation, vertex colors, reflected instance transforms, invalid topology,
unsupported animated profiles, configured limits, and atomic destination preservation.
`AetherOracleFusionCli` writes both PLY and GLB and checks their file signatures.

Address/undefined-behavior sanitizer build and complete suite:

```bash
cmake --build --preset sanitizer --parallel 8
ctest --test-dir build/sanitizer --output-on-failure
```

Result: build succeeded; 11/11 tests passed with no sanitizer report.

Changed-file static analysis using the installed Homebrew LLVM and active Xcode SDK:

```bash
SDK=$(xcrun --show-sdk-path)
/opt/homebrew/opt/llvm/bin/clang-tidy -p build/ci --warnings-as-errors='*' \
  --extra-arg="-isysroot$SDK" \
  --extra-arg="-isystem$SDK/usr/include/c++/v1" \
  engine/mesh/src/GltfExporter.cpp engine/mesh/src/GltfLoader.cpp \
  tools/aether-fuse/main.cpp tests/TestMain.cpp
```

Result: completed with no unsuppressed diagnostic. Two narrow suppressions remain documented in
source: the established CLI `main` exception boundary and the intentional buffer-view/count
parameter order mirroring a glTF accessor.

Formatting, whitespace, shell syntax, and benchmark harness regression tests:

```bash
/opt/homebrew/opt/llvm/bin/clang-format --dry-run --Werror \
  engine/mesh/include/aether/mesh/GltfExporter.hpp engine/mesh/src/GltfExporter.cpp \
  engine/mesh/include/aether/mesh/MeshAsset.hpp engine/mesh/src/GltfLoader.cpp \
  tests/TestMain.cpp tools/aether-fuse/main.cpp
git diff --check
zsh -n tests/fixtures/assert-oracle-fusion.zsh
python3 -m unittest discover -s benchmarks/tests -p 'test_*.py'
```

Result: formatting, whitespace, and shell syntax checks succeeded; 16 Python tests ran, 14 passed,
and 2 dataset-dependent tests were skipped by their existing guards.

During verification, the first exact transform assertion exposed corrupted reflection axes when a
matrix was decomposed by the loader. The exporter now emits validated TRS, preserves mirrored
instances, and explicitly rejects shear; the final suites above include that regression test.
