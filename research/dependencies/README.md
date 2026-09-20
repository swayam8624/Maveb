# S1 Dependency Graph Contract

This directory defines the machine-readable contract for cross-layer minimal-work repair.

The dependency evaluator is deliberately simple: it computes transitive closure. The research difficulty is **not graph traversal**; that mechanism is old. The scientific work is proving or tightly bounding the edges for captured-world reconstruction state, measuring false-positive invalidation, and showing that the resulting closure yields full-rebuild-equivalent output while avoiding hidden global work.

Exact edges should be validated by tiny-scene exhaustive oracles. Conservative edges may over-invalidate but must never miss required downstream state. False negatives are correctness failures.

The current exact reference edge is sparse TSDF block → mesh patch owner, validated by `tsdf-mesh-exact-closure-v0`.
