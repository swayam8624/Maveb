# MAVEB Hypothesis Bank

Generated and filtered: 2026-09-20.

The machine-readable bank contains **119 hypotheses**. It is a record of the search space, not a claim that 119 ideas are novel or correct.

## Final paper filter

The current MAVEB-CLOSURE line freezes the bank into:

| Status | Count | Meaning |
|---|---:|---|
| Locked headline | 5 | Directly defines the current paper claim |
| Required mechanism | 16 | Needed to prove or implement the claim |
| Evaluation / ablation | 6 | Needed to falsify or isolate the claim |
| Deferred follow-up | 92 | Preserved, but outside the current paper line |

The locked problem is:

> **Dependency-certified heterogeneous minimal-work repair for persistent captured worlds.**

The filter rule is:

> Only hypotheses that directly prove, implement, or falsify the locked claim remain active for the current paper.

## Families

- **E — Edit preservation invariants**
- **C — Correspondence and lineage**
- **D — Dependency-minimal world repair**
- **R — Adaptive representation and migration**
- **P — Evidence ledger / temporal truth**
- **X — Change disentanglement**
- **U — Uncertainty after negative results**
- **M — Metal / unified-memory research**
- **S — Versioned spatial storage**
- **B — Bounded heterogeneous scheduling**
- **Q — Metrics and falsification instruments**
- **F — Failure-regime discovery**

The complete taxonomy, falsification experiment, kill condition and final status live in `hypotheses.json`.

## What survived into CBRC

The current line centers the dependency-minimal repair family and pulls in only the supporting mechanisms needed for:

- exact heterogeneous structural closure;
- conservative Gaussian/image bounds;
- stable temporal output bounds;
- calibrated heterogeneous work;
- fail-closed fallback;
- independent full-reference replay;
- baselines and ablations.

Other families remain useful follow-up work, but they do not expand the v1 claim.

## Automatic kill policy

A hypothesis is killed, demoted or deferred when any of the following holds:

1. close prior art substantially contains it;
2. the cheapest falsification probe misses its success condition;
3. the effect disappears on held-out scenes;
4. the purported novel component ablation does not cause the effect;
5. the bound is technically safe but too loose to reduce useful work.

## Navigation

- [Research hub](../README.md)
- [CBRC guide](../../docs/research/CBRC.md)
- [Implementation status](../design/CBRC_IMPLEMENTATION_STATUS.md)
- [Limitations / kill criteria](../design/CBRC_LIMITATIONS.md)
