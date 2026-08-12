# Canonical Asset v1 E2 verification

Date: 2026-08-12
Machine: Apple M2 Pro, 32 GB
Evidence level: E2 deterministic fixture and hostile-input verification

## Proved in this tranche

- A `.aether` package can use a canonical metric textured mesh as its primary representation
  without a base-Gaussian chunk.
- Canonical packages use package version 1.1; existing Gaussian-only packages remain version 1.0.
- The canonical profile carries an embedded material-bound GLB, calibrated cameras, one explicit
  confidence value per vertex, metre/frame declarations, and geometry/appearance provider hashes.
- Camera and confidence codecs round-trip through compiler-independent little-endian records.
- Pack and inspect reject malformed codec headers, hostile relative paths, symlink escapes,
  non-rigid camera transforms, invalid confidence, external GLB resources, mismatched counts, and
  canonical chunks mislabeled as package version 1.0.
- Two independent packages built from identical canonical inputs have the same SHA-256.

## Commands and results

```bash
cmake --preset ci
cmake --build --preset ci --parallel 12
ctest --preset ci --output-on-failure
```

Result: 11/11 tests passed, including `AetherCanonicalAssetCli`.

```bash
cmake --preset sanitizer
cmake --build --preset sanitizer --parallel 12
ctest --test-dir build/sanitizer --output-on-failure
```

Result: 11/11 tests passed under AddressSanitizer and UndefinedBehaviorSanitizer.

```bash
python3 -m unittest discover -s benchmarks/tests -p 'test_*.py'
```

Result: 16 tests passed; two dependency-qualified tests were skipped on this invocation.

Changed-file Clang analysis was run with the active Apple SDK explicitly supplied and
`--warnings-as-errors='*'` over the canonical module, package writer, pack/inspect CLIs, and
foundation tests. The installed LLVM 22 analyzer's false positive for fastgltf's bitmask-enum
operators was disabled; all other checks remained enabled. Result: zero project diagnostics. C++
formatting, Python bytecode compilation, and `git diff --check` also passed. Hosted CI uses its
pinned LLVM 18 analysis configuration without that local exclusion.

The generated fixture package semantically inspected as:

```text
packageVersion: 1.1
chunks: metadata, canonical-asset, canonical-mesh, cameras, canonical-confidence
canonical cameras: 1
canonical confidence values: 3
mesh: 3 vertices, 1 triangle, embedded PNG texture, bound PBR material
```

Independent package SHA-256 values matched:

```text
fe44e2a3505282cca92d146dd5f79b2ddd2d5fcc68df1d3b6a3cc975db2bbc6b
```

## Not proved

- No Sony and iPad capture has yet been registered into one metric frame.
- Uniform fixture confidence is a contract test, not measured sensor confidence.
- The package does not yet implement native GLB export, texture baking, or canonical-to-proxy
  simplification.
- AetherStudio does not yet render the canonical mesh directly from a `.aether` chunk.
- This tranche does not claim geometric accuracy, texture quality, or real-scene E3 evidence.
