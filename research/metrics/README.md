# MAVEB Research Metrics

These metrics are research instruments, not marketing scores.

## Certified QoI error

For each declared quantity of interest:

```
actual = measured full-reference error
bound  = emitted conservative certificate
epsilon = frozen experiment tolerance
```

A certified row must satisfy:

```
actual <= bound <= epsilon
```

Any `actual > bound` is a certificate violation.

## Effectivity

Certificate tightness is reported as:

```
effectivity = certified_bound / max(actual, epsilon_floor)
```

A valid certificate should not systematically fall below one. Extremely large values indicate a safe but potentially useless bound.

## Unchanged World Damage (UWD)

UWD measures damage **outside the intended changed/edit region**.

Geometry displacement and render-space error remain separate distributions (mean/RMSE/p95/max). A method cannot hide geometric damage behind good pixels or vice versa.

## Update Locality Ratio (ULR)

For each native work counter:

```
ULR_component = incremental_work / equivalent_full_rebuild_work
```

Examples include:

- observations inspected;
- TSDF blocks read/written;
- mesh cells or patches regenerated;
- Gaussian primitives inspected/updated;
- texture pages/texels rewritten;
- material states updated;
- GPU publication bytes;
- temporal pixels invalidated.

Different physical units are **never summed by default**.

## Calibrated scalar work

When the planner needs one scalar cost, a frozen `WorkCostModel` maps each native unit into one common unit, normally milliseconds.

The model must be calibrated on isolated pre-evaluation microbenchmarks and frozen before final outcomes are inspected.

A non-zero ledger domain without a coefficient fails closed.

## Representation Churn

Counts births, deaths and representation switches relative to all identities present in either revision.

High churn can reveal an unstable adaptive-representation policy even if frame-level quality looks acceptable.

## Identity Survival

Given a ground-truth correspondence token set, reports correct survival, identity switches and missing identities.

It should be paired with a downstream task metric rather than treated as a standalone success score.

## Reporting rule

Every result table must expose the raw counters and QoI values behind aggregate claims.

No hidden weighted score may replace:

- actual error;
- certified bound;
- epsilon;
- raw locality counters;
- full-reference counters;
- cost-model version;
- fallback decision.
