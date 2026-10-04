# MAVEB Surviving Research Directions

**Date:** 2026-09-20
**Rule:** survival means "worth the next falsification step", not "novel" and not "paper-ready".

## Tier A — candidate headline contributions

### A1. Certified geometry-preserving local Gaussian editing
**Survives narrowly.**

What remains plausible is not "phase preserves geometry." Raw anisotropic opacity-weighted phase was
rejected. Canonical center-field phase survives only as one conditional descriptor.

The strongest formulation now is:

> Given an explicitly isolated local geometric support, can an edit operator change the target
> region while producing a computable certificate/bound on off-target geometry under stated model
> assumptions?

Evidence so far:
- raw Gaussian-field phase rejected under covariance/opacity nuisance;
- canonical phase survives split/merge synthetic attacks reasonably well;
- canonical phase only marginally beats plain canonical density L2 on harder deformation ranking;
- phase recovers coherent translation and supports a conditioning-based weighted-LS error bound;
- partial-motion contamination breaks standalone max-displacement certification.

**Next kill test:** support partitioning / multi-component neighborhoods. If phase loses its analytic
advantage or simpler direct geometry constraints dominate, drop phase from the method.

### A2. Dependency-certified heterogeneous minimal-work world repair
**Strongest systems survivor.**

The distinction is now explicit:

> semantic locality is not computational locality.

Known hidden-global work:
- PR #28 Gaussian selection scans every primitive;
- Metal sparse TSDF snapshot path still has broad readback boundaries;
- TextureBaker is globally coupled by depth, candidate search, exposure and atlas addressing;
- GaussianPipeline scene reload rebuilds/copies the full Gaussian buffer state;
- WorldArchive rewrites complete full-snapshot history.

Positive leverage already exists:
- exact local sparse-TSDF → mesh patch rebuilding;
- persistent dirty RegionKeys / stable world IDs;
- synthetic RegionKey indexing removes the hidden O(N) Gaussian-selection scan;
- persistent index maintenance survives small changed fractions cheaply in the synthetic probe.

A paper-worthy claim requires an end-to-end **Update Locality Ratio** and full-rebuild-equivalent
quality where equivalence is claimed. Local components alone are not sufficient.

## Tier B — mechanisms that may become part of A1/A2

### B1. Resampling-stable lineage/correspondence
Generic persistent identity is occupied by prior work. It remains useful only if split/merge/prune/
densify correspondence improves a downstream certificate, change decision, or historical edit.

### B2. Explicit observability / contradiction evidence
This is currently a correctness requirement, not novelty. PR #28 drops unmatched previous entities
from the next snapshot, causing false removals under partial observation in the synthetic probe.
Modern long-term mapping literature already contains existence/visibility reasoning, so MAVEB must
implement it cleanly without claiming the concept itself.

### B3. Stable texture addressing
The current ordinal atlas fundamentally violates update locality. Stable patch/page addressing is a
required subsystem for A2, not a standalone research contribution.

### B4. Patchable/stable-slot Gaussian GPU records
The current renderer rebuilds the full canonical Gaussian record buffer on load. Stable slots or
region chunks may make revision application local. This becomes scientifically relevant only as one
layer of the end-to-end dependency closure.

### B5. Delta/checkpoint world history
Necessary for a real persistent world; generic journaling is not novel. Exact reconstruction of any
revision must remain possible.

## Tier C — must pass offline oracle before implementation

### C1. Temporal representation migration
Do not build an online migration policy yet.

The repo now contains an exact small-scene offline oracle harness. Feed it **measured** per-region
TSDF/mesh/Gaussian quality/memory/render/update costs. If the mixed oracle does not materially beat
the best fixed feasible representation on held-out scenes, kill migration immediately.

## Ideas killed as headline contributions

- generic local Gaussian update;
- generic selective Gaussian editing;
- primitive-space Gaussian change detection;
- generic persistent Gaussian/object identity;
- fixed mesh+Gaussian hybrid;
- generic bounded-compute continual Gaussian scheduling;
- mobile/Metal Gaussian renderer or port;
- incremental mesh update from Gaussian state;
- raw anisotropic opacity-weighted spectral phase as a geometry-only invariant.

## Current research sequence

1. Get `research/maveb-discovery-persistent` green and run the in-repo Gaussian locality benchmark.
2. Add explicit observability semantics before trusting persistent deletion/reappearance.
3. Measure same-cardinality GPU record patching on Apple silicon.
4. Build stable texture addressing or prove texture repair cannot remain exact/local.
5. Assemble cross-layer work counters and ULR.
6. In parallel, continue the geometry-certificate track with support partitioning and direct-geometry
   baselines.
7. Run the representation migration oracle only after real per-region measurements exist.
8. Only then choose 1-2 finalist paper directions.
