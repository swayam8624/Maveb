# MAVEB Novelty Matrix — Living Document

**Refresh date:** 2026-09-20
**Status:** preliminary collision map, not a novelty claim.

The rule is strict: an idea remains **unverified** until literature and experiments support a concrete distinction.

| Candidate family | Close work already does | What it does not obviously establish | MAVEB leverage | Current decision |
|---|---|---|---|---|
| Generic local continual Gaussian update | CL-Splats localizes optimization/history; GaussianUpdate continually updates changing scenes; GaME adapts evolving RGB-D maps | Heterogeneous TSDF→mesh→Gaussian dependency-minimal recomputation with explicit work accounting | Dirty sparse TSDF/meshing + hybrid stack + PR #28 | **Generic form killed.** Only a stronger cross-representation mechanism remains interesting. |
| Generic bounded-compute continual GS scheduler | EliGSiR (2026-09-17) schedules views, supervision fidelity and geometry growth under bounded compute | Cross-representation dependency jobs or a stronger formal guarantee | TSDF + mesh + Gaussian + render resources | **Generic H6 killed/pivoted.** |
| Generic persistent Gaussian/object identity | Consistent Instance Field calibrates Gaussian identities; long-term semantic maps associate/reactivate instances | Representation-invariant correspondence through split/merge/prune/resample tied to geometry/update guarantees | PR #28 stable IDs + ownership + deterministic oracles | **Generic identity killed.** Lineage only survives if it produces downstream gains. |
| Primitive-space change detection | GD-DIFF compares position/covariance/color with anisotropic drift and observability; separates geometry vs appearance | Transactional heterogeneous revision semantics and causal dependency repair | Reality Diff + provenance + TSDF/mesh/Gaussian | **Primitive change alone killed.** |
| Local 3DGS editing | GaussianEditor, SC-GS, EditSplat, InterGSEdit support local/semantic/geometric-consistent editing | Explicit definition of unchanged geometry outside Ω plus representation-change correspondence and a certificate/bound | CPU/GPU Gaussian oracles + geometry stack | **Priority survivor; novelty unverified.** |
| Spectral/phase geometry signature | Fourier point-cloud work links phase to geometry; FreGS uses frequency regularization; holographic work uses complex phase | Ordinary-3DGS local-edit preservation using phase/graph phase with bounded off-target disturbance | Deterministic Gaussian math + synthetic ground truth | **High-priority cheap probe. Must beat simpler invariants or die.** |
| Fixed mesh+Gaussian hybrid | SuGaR and multiple mesh-Gaussian systems combine representations | Continual evidence-driven representation migration under quality/time/memory/update constraints | Proxy + TSDF + Gaussian + snapshots | **Generic hybrid killed; migration remains plausible.** |
| Adaptive per-region representation migration | Neighboring hybrids assign/bind roles, usually for one reconstruction objective | A region switching TSDF↔mesh↔Gaussian as evidence/cost/change regime evolves | Three existing representation layers | **Priority survivor; offline-oracle probe first.** |
| Minimal-work world repair | Continual-GS localizes Gaussian work; incremental meshing localizes mesh work | One observation→derived-artifact dependency closure spanning TSDF, mesh, Gaussians, textures and render state while matching full rebuild | Dirty meshing + persistent branch + AETHER packages | **Priority survivor if distinction holds.** |
| Evidence/provenance ledger | Visibility/confidence/existence signals occur in several systems | Reversible support/contradiction evidence that measurably improves deletion/reappearance/stale-geometry behavior | Provenance hashing + frozen evidence discipline | **Medium priority; bookkeeping alone is not research.** |
| Naïve sensor-confidence weighting | MAVEB's own U3–U6b falsified several monotonic transfer rules | A different causal leverage mechanism may exist | Calibration + negative-results archive | **Do not rescue old claim. New untouched evaluation required.** |
| Generic mobile/Metal acceleration | SEELE, Mobile-GS, MetalSplatter, gsplat-mlx cover mobile/Apple/Metal execution | Possibly a genuinely unified-memory-specific algorithmic design | Native Metal + unified memory | **Secondary only. Porting is not novel.** |

## Priority questions

### Q1 — Can a local Gaussian edit carry a geometric preservation certificate?
Change Ω while bounding disturbance in Ωᶜ and a boundary band. Compare phase/graph phase against raw center constraints, pairwise-distance invariants, graph-Laplacian descriptors, covariance moments, mesh/surface anchors and rigidity.
**Kill condition:** phase is less stable under resampling/split-merge than a simpler descriptor, or phase loss does not predict actual off-target geometry.

### Q2 — Can MAVEB update the smallest dependency closure of a heterogeneous captured world?
A new observation invalidates spatial evidence → TSDF blocks → mesh patches → Gaussian clusters → textures/materials → render resources. This must beat simple local/full rebuild on work while retaining quality.
**Kill condition:** dependency overhead erases savings or quality diverges from full rebuild.

### Q3 — Can scene regions migrate representation over time?
An uncertain region may remain volumetric, become mesh when geometry stabilizes, retain Gaussian residual appearance, then compress/hierarchize when stable.
**Kill condition:** an offline oracle shows no meaningful Pareto gain over the best fixed representation.

### Q4 — Can persistent correspondence survive Gaussian resampling?
Lineage/neighborhood correspondence should survive split, merge, prune and densify and improve editing/change reasoning.
**Kill condition:** it is not materially better than nearest-neighbor/covariance matching or gives no downstream gain.

## Novelty kill switches already triggered
- Local Gaussian update — occupied by CL-Splats/GaussianUpdate/GaME.
- Bounded-compute Gaussian scheduling — occupied in substantial form by EliGSiR.
- Primitive-space Gaussian change detection — occupied by GD-DIFF.
- Persistent Gaussian/object identity — occupied in substantial forms by Consistent Instance Field and long-term semantic mapping.
- Mesh + Gaussian hybrid — broadly occupied.
- Mobile/Metal Gaussian renderer — broadly occupied.

These can be components, not headline claims.
