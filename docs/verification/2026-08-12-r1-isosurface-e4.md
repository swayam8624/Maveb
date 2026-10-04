# R1 isosurface correctness evidence — E4

Date: 2026-08-12

This record closes the synthetic extractor-correctness portion of R1. It does not upgrade the
existing real ARKitScenes capture or claim that its measured accuracy meets the original R1 target.

## Implemented proof

- `ReferenceMarchingCubes` owns a separately licensed classic 256-case topology table and shares no
  triangulation logic with the resolved production extractor.
- Every table entry is terminated correctly, contains at most five triangles, references only
  sign-changing edges, and extracts the exact declared triangle count.
- The production extractor successfully handles all 254 non-empty/non-full cases without invalid
  topology.
- An embedded checkerboard shared face produces no boundary or non-manifold edge in either path.
- Analytic sphere, box, 30 mm thin wall, two disconnected spheres, and torus fields verify p95
  surface error, closed edges, manifoldness, component count, and Euler characteristic.

The deterministic raw result is committed at
`benchmarks/evidence/r1-oracle-m2-pro-2026-08-12.json`. The executable regenerates the same schema at
`build/ci/test-artifacts/r1-oracle-geometry.json` during CTest.

## Measured result

The grid uses 10 mm voxels. Production sphere error is 0.068 mm mean, 0.162 mm p95, and 0.180 mm
maximum. The sphere is closed and manifold with one component and Euler characteristic 2. Every
other closed analytic fixture also has zero boundary edges and zero non-manifold edges; two spheres
produce two components/Euler 4, and the torus produces one component/Euler 0.

## Verification commands

```text
cmake --preset ci --fresh
cmake --build --preset ci --parallel 1
ctest --preset ci --output-on-failure
Result: 11/11 passed

cmake -S . -B build/r1-sanitizer -G Ninja -DCMAKE_BUILD_TYPE=Debug \
  -DAETHER_BUILD_STUDIO=OFF -DAETHER_ENABLE_ASAN=ON \
  -DAETHER_WARNINGS_AS_ERRORS=ON
cmake --build build/r1-sanitizer --parallel 1
ctest --test-dir build/r1-sanitizer --output-on-failure
Result: 11/11 passed

./build/ci/tests/AetherOracleGeometryTests \
  --json-output build/ci/test-artifacts/r1-oracle-geometry.json
Result: passed; generated JSON is byte-identical to the committed raw report

.aether-deps/proxy-venv/bin/python -m unittest discover \
  -s benchmarks/tests -p 'test_*.py'
Result: 16/16 passed

clang-tidy -p build/r1-ci --warnings-as-errors='*' \
  --extra-arg-before=-isysroot --extra-arg-before="$(xcrun --show-sdk-path)" \
  engine/reconstruction/src/DenseTsdfVolume.cpp \
  engine/reconstruction/src/ReferenceMarchingCubes.cpp \
  tests/OracleGeometryTests.cpp
Result: passed with Homebrew LLVM 22.1.8

clang-format --dry-run --Werror <changed C++ sources and headers>
Result: passed with Homebrew LLVM 22.1.8
```

The hosted format job intentionally uses LLVM 18. That exact formula is not installed locally, so
LLVM 18 formatting remains a hosted-CI confirmation; the newer local formatter reports no change.

## Remaining R1 gate

The 30-frame public ARKitScenes slice currently measures 18.35 mm median and 29.19 mm p95 surface
error. Those values exceed the original 5 mm / 15 mm target. The dense grid's forced voxel growth
is already documented as the architectural reason to proceed to sparse CPU and Metal fusion; this
synthetic proof does not disguise that real-capture limitation.
