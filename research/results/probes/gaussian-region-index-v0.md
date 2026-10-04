# Gaussian Region Index v0

This probe asks whether the current PR #28 semantic-locality logic can avoid its hidden full-scene Gaussian scan.

The synthetic benchmark uses the same core spatial decision: map each Gaussian center to a fixed metric RegionKey and select primitives whose RegionKey is dirty. It compares:

1. **full scan** — inspect all N Gaussian centers every update;
2. **persistent spatial index** — look up only dirty RegionKey buckets.

At one million synthetic Gaussians and a one-percent dirty-cell set:

- full scan inspections: **1,000,000**
- indexed inspections: **10,005**
- exact selected-set agreement: **true**
- Linux sandbox full-scan selection: **30.2602 ms**
- Linux sandbox indexed selection: **1.1121 ms**
- initial index build: **212.8212 ms**

The timings are not MAVEB/M2-Pro results. They are only enough to show that the asymptotic leak is real and removable in principle.

The expensive initial build means the next experiment is not "make a hash map." It is **incremental maintenance**: if a world revision moves only a small number of Gaussians, can their RegionKey memberships be updated at cost proportional to changed primitives while keeping memory overhead acceptable?

If not, this direction dies before integration.
