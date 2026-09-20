# MAVEB Novelty Watch

**Last refresh:** 2026-09-20  
**Rule:** discovering close prior art immediately narrows, pivots, or kills the candidate. This file records collisions; it is not a bibliography replacement.

## Hard kill / pivot events

### Generic continual local Gaussian update — KILLED AS HEADLINE
**Closest work:** CL-Splats (ICCV 2025), GaussianUpdate (ICCV 2025), GaME (CVPR 2026), TwinSplat (2026 online/accepted article).

These systems already detect/update changing regions, preserve historical/static content in various ways, and avoid full retraining. MAVEB may use local update as infrastructure, but not as the primary novelty statement.

### Generic bounded-compute continual Gaussian scheduling — KILLED AS HEADLINE
**Closest work:** EliGSiR (arXiv 2609.20348, 2026-09-17).

EliGSiR already treats continual RGB-D Gaussian mapping as a bounded-compute problem with view scheduling, load-adaptive supervision fidelity and targeted geometry growth. A MAVEB scheduler must therefore address a materially different problem such as a heterogeneous dependency DAG across TSDF/mesh/Gaussian/texture/render state, or provide a stronger guarantee.

### Primitive-space scene change detection — KILLED AS HEADLINE
**Closest work:** From Pixels to Primitives / GD-DIFF (arXiv 2605.07203).

Position/covariance/color drift plus observability is already used to detect and type scene changes directly in Gaussian primitive space.

### Generic persistent Gaussian/object identity — KILLED AS HEADLINE
**Closest work:** Consistent Instance Field (CVPR 2026) and long-term semantic Gaussian mapping such as SuperMap.

Persistent identity can remain an enabling mechanism only if MAVEB demonstrates a distinct representation-resampling problem (split/merge/prune/densify) and a measurable downstream benefit.

### Fixed or heuristic mesh + Gaussian hybrid — KILLED AS HEADLINE
**Closest work:** SuGaR, mesh-Gaussian hybrids, MaGS and related work.

The surviving question is temporal/evidence-driven representation migration with a measured Pareto advantage, not merely using two representations.

### Selective Gaussian update for reconstruction/editing — KILLED AS HEADLINE
**Closest work:** Sparse2DGS (CVPR 2025) uses Selective Gaussian Update for sparse-view reconstruction. VDFE (CVPR 2026) localizes edits and selectively updates Gaussians to reduce unintended modification. TwinSplat adaptively modifies only critical changed Gaussians in an incremental digital-twin pipeline.

A MAVEB contribution must not be phrased as "we update only selected Gaussians."

### Incremental explicit mesh update from Gaussians — KILLED AS HEADLINE
**Closest work:** Incremental Online Scene Reconstruction by 3D Gaussian Triangulation (arXiv 2607.10690).

It directly triangulates geometric Gaussians, updates explicit meshes online and freezes fully optimized historical regions. MAVEB's heterogeneous dependency closure must be different from simply incrementally extracting/updating mesh.


### Fourier/phase-correlation point-cloud registration — KILLED AS NOVELTY
**Closest work:** frequency-domain point-cloud registration (2019), efficient low-frequency 3D shift estimation by phase correlation (ISPRS 2020), robust global point-cloud registration with 3D Fourier/phase correlation (ISPRS JPRS 2021), plus later PHASER-family spectral registration.

The Fourier shift theorem, voxelized point-cloud phase correlation, low-frequency phase fitting, and robustness to noise/uneven density are established prior art. MAVEB may use phase correlation as a baseline or mathematical tool, but **translation recovery from spectral phase is not novel**.

The only surviving phase question is stricter: can a geometry-canonicalized *local* spectral constraint provide a useful and measurable certificate/bound on unintended edit damage outside an authored region, and beat simpler geometric invariants under Gaussian split/merge/prune/densify? If not, kill the phase family entirely.


### Broad certified 3DGS rendering — KILLED AS HEADLINE
**Closest work:** Abstract Rendering (NeurIPS 2025 spotlight) computes provable rendered-image bounds for 3D Gaussian Splats and NeRF under continuous camera/scene uncertainty, explicitly handling projection, sorting and cumulative alpha aggregation and scaling to scenes with up to one million Gaussians.

Therefore MAVEB cannot claim "certified Gaussian rendering" in general.

The alpha-mass candidate survives only as a specialized question: can a concrete pre/post *edited subset* be certified against protected pixels/views with a substantially simpler and tighter bound cheap enough for an interactive editor? This must be benchmarked against Abstract Rendering or clearly shown to solve a different contract.

## Current surviving distinctions to attack

### A. Certified geometry-preserving local editing
Potential distinction: define an explicit geometric preservation contract outside edit region Ω, preserve correspondence under representation resampling, and derive/compute a useful disturbance bound or certificate.

**Threats:** VDFE, GaussianEditor variants, SC-GS, EditSplat, InterGSEdit already optimize locality/consistency and sometimes explicitly minimize unintended non-target modifications.

**Therefore:** visual locality or freezing non-target splats is insufficient. The contribution needs a geometry quantity, a bound/certificate, and a comparison against simpler invariants.

### B. Dependency-certified heterogeneous minimal-work repair
Potential distinction: causal closure from observation/change → spatial evidence → TSDF → mesh → Gaussian → texture/material → render resources, with no hidden full-world scans/copies and with output equivalence to a full rebuild where claimed.

**Threats:** CL-Splats/GaME/TwinSplat localize Gaussian work; incremental Gaussian triangulation localizes mesh update; MAVEB already localizes TSDF→mesh internally.

**Therefore:** the only interesting claim is cross-layer work minimality / near-minimality plus quality equivalence, measured with explicit work counters.

### C. Temporal representation migration
Potential distinction: a region changes representation over time as evidence, update rate, view dependence and resource budgets change.

**Threats:** many hybrid representations and LOD systems already select/compose representations.

**Therefore:** first prove an offline oracle Pareto advantage across a temporal sequence. Kill immediately if the best fixed representation is already Pareto-optimal.

### D. Resampling-stable geometric correspondence
Potential distinction: correspondence is defined above primitive indices and survives split/merge/prune/densify, then measurably improves a downstream edit/change task.

**Threats:** persistent semantic identities and Gaussian instance fields already exist.

**Therefore:** correspondence accuracy alone is not enough; it must solve representation-resampling identity and cause downstream benefit.

## Phase-specific kill event from MAVEB probes

### Raw anisotropic opacity-weighted spectral phase — REJECTED
MAVEB probe `phase-representation-nuisance-v1` held centers fixed while perturbing covariance and opacity. The nuisance moved raw field phase more than the tested center edits (edit-vs-nuisance AUC 0.453).

The only remaining phase candidate is a **geometry-canonicalized** descriptor that explicitly removes appearance/footprint nuisance before spectral analysis. Even that candidate remains unvalidated against split/merge and simpler geometry descriptors.

## URLs tracked in this refresh

- VDFE, CVPR 2026: https://openaccess.thecvf.com/content/CVPR2026/html/Zhang_VDFE_Difference-Aware_3D_Scene_Editing_with_Non-Intrusive_Video_Diffusion_Priors_CVPR_2026_paper.html
- Incremental Online Scene Reconstruction by 3D Gaussian Triangulation: https://arxiv.org/abs/2607.10690
- TwinSplat repository: https://github.com/FredyHKU/TwinSplat
- Sparse2DGS, CVPR 2025: https://openaccess.thecvf.com/content/CVPR2025/html/Wu_Sparse2DGS_Geometry-Prioritized_Gaussian_Splatting_for_Surface_Reconstruction_from_Sparse_Views_CVPR_2025_paper.html

Refresh this repeatedly. A surviving idea can be killed at any time by stronger prior art.
