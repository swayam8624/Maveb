# 2026-08-12 Sony+iPad sensor-alignment evidence — E2

This record covers deterministic synthetic artifact evidence for robust cross-device camera
alignment. It is not E3 evidence from the project owner's Sony and iPad recordings.

## Implemented contract

- Strict COLMAP text-camera parsing with camera-to-world inversion, relative-name safety, duplicate
  rejection, finite/unit quaternion checks, alternating-line validation, and bounded input.
- Complete `.mavebcapture` replay, including every recorded plane size/hash check, before any pose
  is admitted to alignment.
- Versioned one-to-one COLMAP-image to capture-frame mapping.
- Seeded position/orientation RANSAC, near-collinear trajectory rejection, Huber refinement, positive
  scale limits, and explicit median/p95 quality gates.
- Atomic schema-v1 metric camera-rig report containing provenance hashes, Sim(3), residuals,
  rejected matches, issues, and every transformed COLMAP camera.
- Machine-readable errors, deterministic seed, `--dry-run`, and a non-zero quality-gate exit.

## Fixture evidence

The fixture builds twelve arbitrary-scale COLMAP cameras, applies a known `2.35` scale plus a
non-axis-aligned 37-degree world rotation and metric translation, adds millimetre position noise,
and corrupts two matched iPad poses. The engine and black-box CLI both recover the transform, retain
ten inliers, reject both outliers, stay below 3 mm p95 position error, and produce byte-identical
reports on repeated runs. Additional cases reject duplicate mappings, degenerate quaternions, and a
collinear camera path; dry-run proves destination non-mutation. A deliberately strict inlier-ratio
gate exits non-zero while preserving an explicitly rejected diagnostic report.

Verification commands for this tranche:

```bash
cmake --preset ci
cmake --build --preset ci --parallel
ctest --preset ci --output-on-failure

cmake --preset sanitizer
cmake --build --preset sanitizer --parallel
ctest --test-dir build/sanitizer --output-on-failure
```

The exact executed results belong in the review handoff. The E3 gate requires the paired physical
recording, robust residual report, metric Sony camera inspection, and downstream LiDAR/texture test.
