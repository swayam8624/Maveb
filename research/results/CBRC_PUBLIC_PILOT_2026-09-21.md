# CBRC public real pilot — frozen milestone (2026-09-21)

Reference method/semantics were merged to `main` at
`5c6d8c0ca9a69089a74d7132308045c306a64a72`.

The zero-input public RGB/COLMAP pilot used the pinned GraphDECO
Tanks & Temples bundle and the Train/Truck sparse reconstructions. A local
M2 Pro execution of the merged semantics reported:

- 5 frozen real revision rows across 2 scenes;
- 4 certified local repairs;
- 1 automatic FULL fallback;
- 0 certificate violations;
- native/Python planner parity: pass;
- high-coupling coverage: pass;
- median selected temporal/output work / FULL:
  `0.020768229166666666`;
- corresponding single-domain work-reduction factor:
  `48.15047021943574x`;
- median Gaussian update ratio:
  `0.026550985649483147`;
- median GPU-publication byte ratio:
  `0.026550985649483147`;
- median temporal invalidation ratio:
  `0.020768229166666666`;
- median Gaussian inspection ratio: `1.0`.

The `48.15x` value is **not an end-to-end runtime speedup**. It was produced
by the pre-calibration `temporal-pixel-work-v1` scalar work model. The
inspection ratio of 1.0 is therefore recorded as a systems limitation rather
than hidden.

A GitHub-hosted macOS rerun of the zero-input public workflow also completed
successfully after the same semantics were merged. The hosted run is a
reproducibility check, not an additional independent dataset.

This pilot is retained as the first real-data milestone. Campaign-v2 must not
replace, retune, or retroactively cherry-pick these five cases.
