# MAVEB Research Metrics

These metrics are research instruments, not marketing scores.

## Unchanged World Damage (UWD)

UWD measures damage **outside the intended changed/edit region**. Geometry displacement and render-space error remain separate distributions (mean/RMSE/p95/max). A method cannot hide geometric damage behind good pixels or vice versa.

## Update Locality Ratio (ULR)

For each work counter:

```
ULR_component = incremental_work / equivalent_full_rebuild_work
```

Examples include Gaussian primitive inspections, TSDF blocks fused/read back, mesh patches rebuilt, bytes uploaded, texture texels rewritten, GPU kernels dispatched, or measured milliseconds.

Different physical units are **never summed by default**. A single aggregate ULR is legal only when the experiment supplies explicit cost weights that map counters to a common cost model.

## Representation Churn

Counts births, deaths, and representation switches (for example TSDF→mesh or Gaussian→mesh) relative to all identities present in either revision. High churn can reveal an unstable adaptive-representation policy even if per-frame quality is good.

## Identity Survival

Given a ground-truth correspondence token set, reports correct survival, identity switches, and missing identities. This is intended for split/merge/prune/densify stress tests and should be paired with a downstream task metric.

## Rule

Every result table must expose the raw component counters used by these metrics. No hidden weighted score may replace the underlying measurements.
