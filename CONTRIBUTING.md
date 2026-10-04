# Contributing to AETHER

## Development contract

- Keep `main` buildable and land work through milestone-sized branches.
- Do not commit datasets, captures, generated build directories, credentials, signing keys, or
  machine-specific paths.
- Public C++ APIs require ownership, threading, input/output, failure, coordinate-system, and
  degeneracy documentation where applicable.
- Shared C++/MSL layouts require compile-time size and offset assertions.
- New render passes must declare all reads and writes through the render graph.
- Performance claims require committed benchmark configuration and raw JSON/CSV evidence.
- Research claims require baselines, ablations, limitations, and reproducible seeds/configuration.

## Before opening a change

```bash
cmake --preset ci
cmake --build --preset ci
ctest --preset ci
cmake --preset sanitizer
cmake --build --preset sanitizer
ctest --test-dir build/sanitizer --output-on-failure
```

Changes touching the renderer must additionally build `debug`, launch AetherStudio, and run the
relevant Apple-silicon GPU validation checklist. Do not weaken warnings or validation globally to
silence third-party code; mark pinned external headers as system headers instead.
