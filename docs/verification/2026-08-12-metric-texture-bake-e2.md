# Metric texture bake E2 verification — 2026-08-12

Evidence level: **E2 fixture-tested**, not real-capture verified.

The committed black-box fixture constructs a metric two-triangle PLY, an accepted camera rig, an
OpenCV-calibrated 64x64 image, and runs the shipping CLI through image decode, visibility baking,
PNG encode, native GLB export, and native GLB re-import. A second run must be byte-identical. The
fixture also verifies image and GLB hashes in the atomic provenance, dry-run isolation, and rejection
of a non-accepted metric rig. The engine fixture separately proves global exposure compensation and
that a rear surface is rejected behind a front surface.

Required commands before review:

```bash
cmake --build --preset ci --parallel
ctest --preset ci --output-on-failure
cmake --build --preset sanitizer --parallel
ctest --test-dir build/sanitizer --output-on-failure
python3 -m unittest discover -s benchmarks/tests -p 'test_*.py'
```

Real paired Sony/iPad imagery remains required for E3. No synthetic result in this tranche is a
claim about real seam quality, calibration residuals, coverage, memory, or runtime.
