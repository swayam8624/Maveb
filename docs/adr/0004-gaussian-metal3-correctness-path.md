# ADR 0004: Keep a bounded Metal 3 correctness path beside the optimized sorter

- Status: Accepted
- Date: 2026-07-12

## Decision

The standard Gaussian renderer first lands as a complete Metal 3 pipeline with projection,
anisotropic covariance, culling, overlap counts, exclusive offsets, key generation, stable 8-pass
radix ordering, tile ranges, front-to-back composition, depth, IDs, early termination, and bounded
overflow counters. It uses only 32-bit atomics and therefore remains valid on the M1 baseline.

Serial exclusive scan and 8-bit stable radix kernels remain available as deterministic fallbacks.
The default path uses 256-threadgroup Blelloch scans, block-prefix propagation, saturated global
budgets, indirect dispatch, and a stable 16-pass 4-bit radix made of per-group histograms, group
prefixes, and SIMD-prefix scatter. A Metal test crosses three scan/radix blocks with shuffled depths
and varying colors, then compares the composed result to the CPU oracle.

## Consequences

- Every stage and compatibility fallback is executable; optimization does not change public scene
  or shader ABI.
- Tile-entry allocation is explicitly budgeted. Overflow is counted and never writes out of bounds.
- No performance claim or Phase 3 exit gate may cite the serial fallback or tiny fixture.
- M1 compatibility does not depend on 64-bit atomics.
