# Offline video input and sparse-model selection — E2

Date: 2026-08-12
Machine: Apple M2 Pro, 32 GB
Evidence level: E2 deterministic fixtures and integration tests

## Scope proven

- `aether-keyframes` decodes bounded ImageIO thumbnails and deterministically reports blur,
  exposure, contrast, spacing, duplicate, discontinuity, and useful-change decisions.
- Keyframe outputs publish as one directory replacement and contain an ordered relative image list
  plus a versioned per-frame JSON report.
- Video input defaults to COLMAP sequential matching with a declared local overlap; unordered
  photographs default to exhaustive matching.
- Per-folder camera grouping requires a versioned manifest and rejects missing, duplicate,
  uncovered, traversing, root-level, or nested groups.
- Every numeric COLMAP sparse model is exported and validated. A malformed candidate cannot hide a
  passing sibling model. Registered image names must belong to the exact selected list. Selection
  is deterministic and emits its ranking reason.
- The selected model is exposed at `sparse/selected-text`; proxy generation and undistortion consume
  the same winning model.
- Input kind, matcher, overlap, camera mode, camera groups, image list, and preprocessing manifest
  participate in schema-v4 provenance and resume identity.
- A subprocess failure records `status: failed` and `failedStage` rather than leaving a running job.
- MavebBench now decodes video candidates at 12 FPS, validates them, selects keyframes, and passes
  the selected list and preprocessing manifest into sequence-aware reconstruction.

## Verification executed

```text
cmake --preset ci
cmake --build --preset ci --parallel 12
ctest --preset ci --output-on-failure
```

Result: 15/15 passed, including keyframe CLI replacement, video/multi-camera contracts,
multi-model selection, failed-job persistence, and matcher-sensitive resume identity.

```text
cmake --preset sanitizer
cmake --build --preset sanitizer --parallel 12
ctest --test-dir build/sanitizer --output-on-failure
```

Result: 15/15 passed with AddressSanitizer and UndefinedBehaviorSanitizer enabled.

```text
<pinned proxy Python> -m unittest discover -s benchmarks/tests -p 'test_*.py' -v
```

Result: 17/17 passed with NumPy available; no skipped evaluation tests.

```text
git diff --check
zsh -n <changed shell fixtures>
python3 -m py_compile <changed Python files>
clang-format --dry-run --Werror <all changed and untracked C/C++ sources>
```

Result: passed. Exact CI formatting remains LLVM 18 on GitHub; the local installed formatter is
LLVM 22.1.8.

Changed production C++ sources also passed local LLVM 22 clang-tidy with the active Xcode SDK and
warnings as errors. The local compatibility invocation excluded LLVM-22-only exception-escape and
easily-swappable-parameter diagnostics, plus analyzer reports originating inside simdjson. The
repository's exact LLVM 18 changed-file static-analysis gate therefore remains hosted-CI evidence
after publication, not a claimed local result.

## Inspected artifacts

The deterministic keyframe fixture selected 3 of 6 candidate frames and retained every decision.
The multi-model fixture rejected corrupt model `0`, selected model `1`, recorded 48 valid tracks,
published `sparse/selected-text`, and used binary model `1` for undistortion. Multi-camera dry-run
emitted `single_camera_per_folder`; video dry-run emitted `sequential_matcher`, overlap 10, and the
exact image list.

## Open evidence

This is E2, not real-world completion. The following remain open:

1. Run the selector and reconstruction on the user's Sony Alpha 7 V orbit footage.
2. Measure registered-frame ratio, rejection reasons, runtime, peak memory, and final mesh quality.
3. Replace appearance-change heuristics with measured feature/parallax evidence where fixtures show
   false admissions or false rejections.
4. Implement targeted Sony+iPad cross-group matching and robust COLMAP-to-ARKit Sim(3) alignment.
5. Prove metric textured mesh output on the paired Sony and iPad LiDAR capture.
