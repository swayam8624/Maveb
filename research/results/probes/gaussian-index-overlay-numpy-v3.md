# Gaussian index base+delta overlay — NumPy reference probe v3

**Evidence class:** cheap structural probe.
**Not:** production C++, Metal, M2 Pro, real-scene, or paper-level performance evidence.

The probe uses one million deterministic packed region keys and compares a fully rebuilt sorted
index with an immutable sorted base plus a sorted delta/tombstone overlay after cumulative spatial
relocation. Dirty queries sample 0.1% of occupied cells. Every level must return the **exact same
primitive index set** as the fully rebuilt oracle or the probe aborts.

| cumulative relocated | full rebuild | delta rebuild | maintenance ratio | full query median | overlay query median | storage vs full | exact |
|---:|---:|---:|---:|---:|---:|---:|:---:|
| 1% | 105.16 ms | 0.74 ms | 0.70% | 3.05 ms | 7.00 ms | 1.093x | yes |
| 2% | 109.31 ms | 1.73 ms | 1.58% | 3.16 ms | 7.98 ms | 1.103x | yes |
| 5% | 108.19 ms | 3.79 ms | 3.50% | 2.94 ms | 7.18 ms | 1.133x | yes |
| 10% | 102.75 ms | 8.64 ms | 8.41% | 2.71 ms | 7.74 ms | 1.183x | yes |
| 20% | 109.46 ms | 18.36 ms | 16.77% | 2.69 ms | 6.72 ms | 1.283x | yes |
| 40% | 103.04 ms | 37.51 ms | 36.40% | 2.68 ms | 6.23 ms | 1.483x | yes |

Source: `research/probes/gaussian_index_overlay_numpy_v3.py`,
commit `462b27d229cf8d6633e0d51e53c9457644120d95`,
blob `2d344b7d0a6406772d9bf6959648a45ecf4adad7`.

Runtime: Python 3.13.5, NumPy 2.3.5, Linux 6.18.44 x86_64. These timings are only comparable
inside this runtime.

## What survived

The **mechanism** survives its cheap kill test: a small sorted delta can represent small spatial
changes without rebuilding the million-entry base, while preserving exact selection. Maintenance
cost rises approximately with accumulated delta size in this reference.

## What did not become a claim

Overlay lookup is slower than a single rebuilt flat index (roughly 2.0–2.9x here), and storage rises
from about 1.09x at 1% relocation to 1.48x at 40%. Therefore an overlay cannot grow indefinitely.
A compaction threshold/hysteresis policy is required, and the production choice still needs C++ and
M2 Pro measurements against the mutable hash and flat-sorted alternatives.

## Decision

**S7 mechanism survives; no publication claim.**

Next gate: implement the overlay behind the production spatial-index abstraction, preserve exact
ownership-selection semantics, then measure repeated revisions and compaction crossover on the
actual Mac. If production query cost or allocator overhead erases the maintenance benefit, kill the
overlay and retain the simpler structure.
