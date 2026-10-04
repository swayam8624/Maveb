# Representation Migration Offline Oracle

This directory contains a **falsification harness**, not a result.

The migration hypothesis only deserves online implementation if measured per-region data shows that
a mixed TSDF/mesh/Gaussian assignment can outperform the best fixed representation under the same
hard resource budgets.

`representation_migration_oracle.py` therefore solves a small controlled-scene assignment exactly.
It accepts measured candidate quality loss, memory, render time and update time for each region.

The bundled fixture is **synthetic unit-test data only**. Do not cite its output as evidence.

## Required real experiment

1. Partition controlled scenes into stable region IDs.
2. For every region, obtain actual candidate measurements for the same cameras/geometry:
   TSDF/proxy mesh, mesh, Gaussian, and any hybrid residual candidate.
3. Freeze budgets before looking at held-out results.
4. Run the exact oracle.
5. Compare against every fixed representation feasible under the same budgets.
6. Repeat over temporal revisions and held-out scenes.

### Kill rule

If the offline mixed-representation oracle does not materially dominate the best fixed feasible
representation on held-out measured scenes, **stop**. Do not build online migration, learned
policies, hysteresis, or schedulers.
