# Exact TSDF→Mesh Dependency Oracle v0

This probe converts one MAVEB locality mechanism from implementation intuition into an exhaustive tiny-scene check.

For every dirty-block subset of size 1–4 in a 3×3×3 sparse block grid, the script independently compares:

1. the production rule: dirty block + seven negative owner neighbours;
2. an explicit oracle: enumerate every mesh owner patch and ask whether its block-level read support intersects the dirty set.

**20,852 cases were checked. Mismatches: 0.**

A single dirty block expands to at most **8** mesh owner patches at block granularity.

This is useful beyond the mesher itself: S1 now has one exact layer that can serve as the standard for future cross-layer dependency proofs. Higher layers should aim for the same pattern—state precisely what each derived artifact reads, compute the affected closure, and compare against an exhaustive oracle on tiny scenes before scaling.
