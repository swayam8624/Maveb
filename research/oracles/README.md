# Temporal Representation Oracle

This is the **kill-test before implementation** for S3.

MAVEB must not build an online TSDF↔mesh↔Gaussian migration policy until measured offline data shows that temporal representation switching can beat the best fixed representation.

For every stable region and revision, collect real measurements for each feasible representation:

- geometry error,
- render error,
- retained memory,
- render milliseconds,
- update milliseconds,
- migration cost from the previous representation.

The oracle then computes assignments under explicit objective weights. It never fabricates missing costs and does not collapse quality/time/memory into one hidden metric.

## Required comparison

For each sequence and budget regime, compare:

1. best fixed representation for the whole sequence,
2. fixed hybrid rule,
3. per-revision offline oracle,
4. later, only if (3) dominates, an online causal policy.

If the offline oracle cannot materially Pareto-dominate the best fixed strategy, **kill temporal migration** before writing runtime code.
