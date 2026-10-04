# ADR 0003: Apple SIMD is the AETHER scene-math ABI

Status: Accepted — 2026-07-12

## Decision

AETHER uses Apple SIMD types directly for fixed-size scene and rendering math. Matrices are
column-major, multiply column vectors, use right-handed world/view coordinates, and use Metal's
`[0,1]` depth range. Projection matrices use reverse Z.

The adjacent KairoMath implementation was evaluated because it has compatible conceptual
conventions and robust TRS behavior. Its live repository currently has no explicit license file,
so it cannot be linked or vendored into Apache-2.0 AETHER. This decision can be revisited after an
explicit compatible license and a reproducible module-consumer build are available.

## Consequences

- CPU structures map naturally to MSL without an implicit transpose.
- AETHER avoids maintaining a second general-purpose math library.
- Conversion is required if KairoMath becomes a licensed optional dependency because its matrices
  use row-major storage.
