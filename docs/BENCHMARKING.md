# AETHER benchmark contract

`aether-benchmark` is an offscreen Apple-silicon executable. It validates a `.aether` package and a
versioned camera path, loads the same canonical Gaussian representation and offline Metal kernels as
Studio, performs configurable warmup frames, and waits for every measured command buffer. Timing is
read from Metal's GPU start/end timestamps, not estimated from CPU wall time.

The JSON result schema v2 records device name, scene path, resolution, measured/warmup frame counts,
GPU median/p95 milliseconds, synchronized CPU-frame median/p95 milliseconds, source Gaussian count,
peak visible count, peak tile entries, peak bounded overflow, peak early termination, and peak
`currentAllocatedSize` reported by Metal. Counter peaks are accumulated over every warmup and
measured camera frame; an overflow that occurs before the final frame can no longer be hidden.

A run exits non-zero if the configured tile-entry budget overflows. A partial image is never emitted
as a successful benchmark result. The viewer uses the same conservative minimum budget, while the
future LOD controller will make the budget an explicit quality-preset constraint.

`--max-p95-ms` and `--max-memory-bytes` turn acceptance targets into executable gates. Schema-v2
output always reports the individual and combined budget result, and a missed gate exits with code
6 after emitting the complete measurement. The CPU-frame value intentionally includes synchronous
submission and wait time; it is a reproducible end-to-end frame cost, not a claim of pure CPU work.

Camera paths use meters, seconds, radians, EV exposure, and `[x,y,z,w]` unit quaternions. Times must
be finite, non-negative, and strictly increasing. Sampling clamps outside the path and uses linear
position/FOV/exposure plus shortest-path quaternion interpolation.

```bash
aether-benchmark scene.aether --camera-path path.json \
  --width 1920 --height 1080 --frames 600 --warmup 30 --json \
  --max-p95-ms 16.667 --max-memory-bytes 10737418240
```

The default Metal 3 path now uses block-parallel scans and stable 4-bit parallel radix passes, while
retaining serial compatibility kernels. Numbers produced before the named medium benchmark scene and
cross-device validation are useful for regression detection only; they are not AETHER performance
claims.
