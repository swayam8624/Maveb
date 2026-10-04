# ADR 0005: Reconstruction truth and oracle-first recovery

- Status: Accepted
- Date: 2026-07-19

## Context

The first live reconstruction plumbing accepted RGB frames, invented forward camera motion,
modified a pre-populated sphere from image luminance, and exported disconnected quads. Calibration
was loaded but not used by tracking or fusion, and a camera failure silently selected synthetic
frames. Although those components compiled, they did not estimate real geometry.

AETHER's hybrid depth, shadows, collision, and material research require geometrically defensible
proxy surfaces. Treating callback plumbing as reconstruction would invalidate every downstream
claim.

## Decision

The placeholder tracker, volume, live session, Studio bridge, and live controls are removed from
production. Git history is the archive; misleading fixture implementations do not remain under
production names.

Reconstruction proceeds in this order:

1. Versioned recorded metric RGB-D with known camera-to-world poses.
2. Deterministic CPU signed-distance integration and isosurface extraction.
3. Geometry metrics and real recorded-scene evidence.
4. Production capture, tracking, depth estimation, sparse GPU fusion, and live Studio workflow.

Relighting, cinematic, and LOD expansion remains frozen until reconstruction reaches E3. Synthetic
sources must always be selected explicitly. No UI may report fusion unless a valid pose and metric
depth observation updated the volume.

## Contracts

- Capture data is immutable and lifetime-safe.
- Camera coordinates use +Z forward; recorded poses are camera-to-world.
- Depth is float32 metres plus optional uint8 confidence.
- Intrinsics belong to every packet and must match its depth dimensions.
- Unobserved voxels cannot emit geometry.
- Evidence levels retain their literal meanings: E1 compiles, E2 fixture-tested, E3 real-scene
  verified, and E4 publicly reproducible.

## Consequences

The shipping app temporarily loses its live reconstruction controls. The renderer, Gaussian path,
offline COLMAP/Brush orchestration, packaging, and existing hybrid composition remain available.
Live mode returns only after the recorded oracle, real pose/depth path, and soak gates pass.
