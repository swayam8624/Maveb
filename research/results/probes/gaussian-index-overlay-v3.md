# Gaussian Index Base+Delta Overlay Probe v3

**Status:** synthetic Linux/x86 structural probe only. This is not Apple-silicon, Metal, a real captured scene, or publication evidence.

This probe tests the architecture proposed after v2: keep a compact sorted immutable base index,
mark base entries invalid when primitives move, place the current locations of changed primitives in
a compact sorted delta, and compact/rebuild later. Every reported overlay query was checked for
**exact primitive-selection agreement** against a fully rebuilt flat index.

| cumulative relocated Gaussians | full flat rebuild | delta rebuild | maintenance speedup | flat query median | overlay query median | query slowdown | overlay storage overhead |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1% | 102.61 ms | 1.02 ms | 100.35x | 3.27 ms | 4.79 ms | 1.47x | 7.25% |
| 2% | 107.90 ms | 1.94 ms | 55.57x | 3.34 ms | 4.80 ms | 1.44x | 8.25% |
| 5% | 107.24 ms | 4.99 ms | 21.47x | 3.46 ms | 5.12 ms | 1.48x | 11.25% |
| 10% | 107.25 ms | 9.95 ms | 10.77x | 3.67 ms | 5.58 ms | 1.52x | 16.25% |
| 20% | 102.53 ms | 21.69 ms | 4.73x | 3.44 ms | 5.45 ms | 1.59x | 26.25% |
| 40% | 104.44 ms | 45.89 ms | 2.28x | 4.17 ms | 6.91 ms | 1.65x | 46.25% |

Configuration: 1,000,000 primitives, deterministic seed 42, 1% of occupied cells queried, seven
query repeats per level. The compact entry is 16 bytes. Source Git commit:
`78b18a3552b4fcfd12196d7e8a78742d94ceaa44`; Git blob:
`fdb975711995bc4fe72c2738ceb9b3d385be96d5`.

## Interpretation

The hypothesis survives this cheap probe. At small cumulative change fractions, rebuilding only a
sorted delta is dramatically cheaper than rebuilding the million-entry flat index while remaining
bit-for-bit equivalent at the selected-index level. The cost is a second binary lookup path and a
tombstone mask, which made sparse queries about 1.4-1.7x slower in this synthetic layout.

The effect degrades smoothly as the delta grows. By 40% cumulative relocation, delta maintenance
already costs about 44% of a full rebuild and storage overhead is about 46%. That supplies an
empirical reason for **periodic compaction based on delta fraction**, rather than an arbitrary
always-hash or always-rebuild policy.

This does **not** prove that the overlay is the production winner. The next falsification steps are:
measure clustered real-scene keys, additions/removals/repeated moves, delta compaction hysteresis,
actual bytes/allocator overhead in the C++23 implementation, and Apple M2 Pro behavior. It should
also be compared with the mutable hash-bucket index and the flat sorted branch under the same
workload.

## Decision

**SURVIVE AS SYSTEM MECHANISM; DO NOT PROMOTE TO PAPER CLAIM.**

A compact immutable base + bounded mutable delta is now justified strongly enough to implement
behind the Gaussian spatial-index abstraction for an in-repository A/B benchmark. The mechanism
matters only if it lowers end-to-end world-update work after GPU publication, texture/history work,
and quality-equivalence checks are included.
