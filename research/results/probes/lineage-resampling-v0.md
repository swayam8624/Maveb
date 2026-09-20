# Lineage Stress Probe v0

A single resampling step makes nearest-neighbour matching look deceptively strong. The failure appears over repeated revisions.

Synthetic setup:

- 200 initial primitives,
- repeated near-duplicate structures,
- 20 revisions,
- 8% split, 5% merge, 4% prune per revision,
- small re-optimization jitter,
- 30 random seeds.

Sequential nearest-neighbour tracking propagates identity from the immediately previous revision. Ground-truth ancestry is known from the synthetic resampling operations.

At revision 1:

- ancestor recall: **98.59%**
- exact ancestry: **97.35%**

At revision 20:

- ancestor recall: **84.54%**
- exact ancestry: **74.57%**

This establishes a failure regime worth studying. It does **not** establish explicit lineage as a solution, because the oracle currently receives privileged split/merge metadata.

Next S4 gate: beat covariance-aware matching, ICP, optimal transport/set matching and topology descriptors, then show that better correspondence improves a downstream preservation/change task.
