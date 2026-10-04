# Phase Track Decision v3 — Demoted

The phase idea is no longer a primary MAVEB research bet.

## Evidence accumulated

1. **Raw anisotropic/opacity-weighted Gaussian-field phase failed.** Covariance and opacity nuisance moved phase as strongly as or more strongly than actual center edits.
2. **Canonical center-field phase obeys the Fourier shift theorem.** Useful mathematical sanity, not novelty.
3. **Simple moments beat phase on the tested translations**, although moments miss rigid rotations.
4. **Spatial density L2 is already competitive with phase** as a generic change detector.
5. **Known-correspondence rigid edits do not need phase at all.** A Kabsch/Procrustes baseline recovered random rigid transforms to machine precision in a 100-trial synthetic control.

## Surviving niche

Phase can continue only for a substantially harder problem:

> geometry preservation or displacement inference when primitive correspondence is unstable because the Gaussian representation has split, merged, pruned, densified or been independently re-optimized.

Even there, the mandatory baselines are ICP, optimal-transport/set matching, density correlation, surface anchors and graph/geometric descriptors.

If phase does not beat at least one of those on representation-resampling stress tests, kill it completely.

**Current status:** supporting hypothesis, not a candidate headline contribution.
