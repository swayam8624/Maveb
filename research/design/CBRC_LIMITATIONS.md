# CBRC limitations and threat model

This document is part of the experiment contract, not post-hoc reviewer defense.

## Certification assumptions

CBRC is only as sound as its bounds. A certificate is valid only if every exact/discrete dependency needed to reproduce repaired state is included in the hard or predecessor closure; every soft edge used in `K_cert` is non-negative and is a conservative finite-change upper bound over the declared revision domain; the exterior response admits the selected finite/convergent path-sum interpretation; each QoI operator is itself a conservative bound for the output metric being claimed; and implementation arithmetic/indexing preserve those assumptions.

Empirical Jacobians, learned predictors, average-case measurements, or local derivatives without a remainder bound are not certificates.

## Known theoretical limits

The resolvent `(I-K_OO)^-1` is classical machinery, not a mathematical novelty. Generic susceptibility/change propagation and goal-oriented error control have prior art. The research burden is the end-to-end captured-world specialization.

A spectral radius below one is useful for cyclic asymptotic stability but does not describe finite DAG transient fanout. Report transient amplification and accumulated susceptibility separately.

The simple `xi=-1/log(kappa)` relation is valid only for homogeneous exponential contraction. For heterogeneous graphs, estimate shell response directly and fit/report a correlation length only when an exponential model is supported.

The nuclear/free-energy analogies are explanatory only unless they produce an independent theorem or algorithmic advantage.

## Systems limits

Conservative bounds may be too loose to save work. Some revisions are globally coupled by design and should rebuild. CBRC is not an "always incremental" method.

The dense Python implementation is a correctness reference; it is not evidence that a large sparse captured world can solve the same system cheaply. Production overhead must be measured.

Scene representation changes can invalidate previously calibrated bounds. Version edge-bound metadata with representation parameters and invalidate stale certificates.

GPU atomic publication, temporal state, and asynchronous rendering can create hidden dependencies. They must either be encoded as HARD dependencies or explicitly bounded.

## Evaluation threats

Full rebuild is the oracle only if it is deterministic enough for the declared QoI. Record seeds, compiler/runtime versions, camera paths, and numerical tolerances.

Synthetic matrices test theory and phase behavior, not real-world speedup. Real scenes and public evolving-scene workloads are mandatory.

Do not tune epsilon per scene after seeing results. Freeze strict/practical tolerance profiles first. Do not exclude fallback cases; they are a core result.

## Claim wording

Safe after supporting evidence: "Across the evaluated certified revisions, measured QoI error did not exceed the emitted certificate."

Unsafe without a formal proof covering the production stack: "CBRC can never exceed the tolerance."

Safe after supporting evidence: "CBRC selected full rebuild when the certified local cone was not cheaper in our implementation."

Unsafe: "CBRC always finds the global minimum-work cone." The first search is greedy and claims a certified feasible cone, not combinatorial optimality.

## Failure artifacts

Every failed certificate must retain the revision manifest, graph/edge-bound version, chosen cone, emitted bound, full-reference output, actual error, and first violated invariant if known. A violation becomes a regression test before any further result is trusted.
