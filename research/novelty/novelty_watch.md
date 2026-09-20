# Maveb Novelty Watch

Updated: 2026-09-20

This file is a kill-switch ledger, not a claim of novelty. A candidate is downgraded as soon as close prior art occupies the mechanism. The purpose is to keep implementation effort pointed at distinctions that remain testable.

## Current collision summary

| Candidate direction | Current status | Closest collision | Consequence |
|---|---|---|---|
| H1 persistent Gaussian/primitive identity across revisions | WEAKENED / REFORMULATE | Dynamic 3D Gaussians (2023); LTGS (CVPR 2026 Findings) | Persistent identity by itself is not a contribution. Maveb must test identity across intermittent recaptures/reconstruction churn and show that it enables a measurable downstream property such as lower unchanged-world damage or smaller update work. |
| H2 evidence/provenance-aware continual reconstruction | OPEN BUT NARROWING | EliGSiR (2026-09-17), GaussianUpdate, GaME | “Evidence-guided” scheduling/updating is occupied in broad form. A Maveb claim needs a representation-level evidence ledger with explicit support/contradiction/observability and a measurable causal benefit, not generic confidence weighting or view selection. |
| H3 adaptive mesh/Gaussian assignment | WEAKENED / REFORMULATE | MeshGS; Hybrid Mesh-Gaussian Representation for Efficient Indoor Scene Reconstruction | Static hybrid assignment is occupied. The interesting question is continual, region-level representation selection under measured quality/time/memory/update cost. |
| H4 representation migration over time | HIGH-PRIORITY OPEN QUESTION | closest work currently uses fixed or deformation-bound hybrid representations | Do not claim open/novel yet. Search specifically for online mesh↔Gaussian↔volumetric migration and budgeted representation switching. |
| H5 dependency-driven minimum-work updates spanning TSDF→mesh→Gaussian→render state | HIGH-PRIORITY OPEN QUESTION | CL-Splats/GaME localize Gaussian work but do not obviously expose Maveb's heterogeneous dependency closure | Distinction must be demonstrated quantitatively with work touched, bytes rewritten, dirty cells, Gaussians touched and final-quality parity. |
| H6 bounded-compute Gaussian scheduling | COLLISION / DEMOTE AS STANDALONE | EliGSiR (arXiv:2609.20348) | Do not build a paper around generic bounded-compute continual 3DGS scheduling. Retain only as a component or compare against it. |
| H7 quality-per-byte representation allocation | OPEN BUT RELATED TO LOD/COMPRESSION | Mobile-GS; Matryoshka Gaussian Splatting; hybrid mesh/Gaussian work | A static rate-distortion claim is weak. Tie it to region-specific heterogeneous representation and continual migration if experiments support it. |
| H8 calibrated heterogeneous sensor uncertainty | CLOSED AS EFFICACY CLAIM IN CURRENT TRACK | Maveb U1b/U2 positive predictive calibration; downstream U3/U4/U5/U6b negative/null | Preserve the negative-result record. Do not retune exposed confirmation rooms or recycle this into a positive claim. |
| H9 structural vs appearance vs illumination change separation | COLLISION / REFORMULATE | GS-DIFF explicitly separates geometric and appearance change in primitive space | Plain structural-vs-appearance separation is occupied. Lighting disentanglement plus persistent evidence may remain distinct but requires dedicated prior-art search and strong experiments. |
| H10 delta/versioned worlds | ENGINEERING UNTIL PROVEN OTHERWISE | LTGS chronology; CL-Splats previous-state recovery | Storage/history alone is not research. Retain only if delta state plus persistent IDs/evidence gives a measurable algorithmic advantage. |
| H11 unified-memory-aware residency/scheduling | OPEN SYSTEMS QUESTION | Mobile-GS and Metal renderers address deployment, not necessarily persistent captured-world scheduling | Must demonstrate an algorithmic consequence on Apple silicon; “port to Metal” is not a contribution. |
| H12 stable region history / multi-revision query | WEAKENED | LTGS chronology; CL-Splats previous-state recovery | Multi-time query alone is not enough. Couple to delta storage, persistent identities, selective reconstruction or representation migration and measure the resulting advantage. |

## High-impact literature collisions

### Dynamic 3D Gaussians: Tracking by Persistent Dynamic View Synthesis
- arXiv: https://arxiv.org/abs/2308.09713
- Persistent Gaussian identity already exists for dense dynamic scenes: Gaussians persist while position/rotation evolve.
- Kill switch: Maveb cannot claim that “Gaussians that retain identity through time” is itself novel.
- Possible distinction to test: intermittent recaptures and independently reconstructed/evolving worlds where primitive cardinality and support can change, with explicit births/deaths/merges/splits and provenance.

### CL-Splats: Continual Learning of Gaussian Splatting with Local Optimization
- arXiv: https://arxiv.org/abs/2506.21117
- Performs change detection and local optimization while preserving previous states.
- Kill switch: “only optimize changed Gaussian regions” is occupied.
- Maveb distinction, if real: dependency-driven minimal invalidation across heterogeneous TSDF, mesh, Gaussian and render products, evaluated as work fraction versus equivalent full rebuild.

### GaussianUpdate
- arXiv: https://arxiv.org/abs/2508.08867
- Continual Gaussian updates with explicit change handling, visibility-aware continual learning and generative replay.
- Kill switch: generic visibility-aware continual preservation is occupied.

### LTGS: Long-Term Gaussian Scene Chronology From Sparse View Updates
- arXiv: https://arxiv.org/abs/2510.09881
- CVPR 2026 Findings.
- Tracks object-level long-term changes from sparse captures and uses reusable Gaussian object templates across time.
- Kill switch: long-term chronology, object matching and lightweight sparse update are not unique on their own.

### Gaussian Mapping for Evolving Scenes (GaME)
- CVPR 2026: https://openaccess.thecvf.com/content/CVPR2026/html/Yugay_Gaussian_Mapping_for_Evolving_Scenes_CVPR_2026_paper.html
- Code: https://github.com/VladimirYugay/GaME
- Online 3DGS mapping for long-term structural changes with dynamic scene adaptation and stale-keyframe management.
- Kill switch: “continually update a Gaussian world as the environment changes” is occupied.

### GS-DIFF / From Pixels to Primitives
- arXiv: https://arxiv.org/abs/2605.07203
- Direct primitive-space scene change detection using Gaussian attributes and observability; separates geometric and appearance change.
- Kill switch: primitive-space geometric/appearance change classification is occupied.

### Hybrid Mesh-Gaussian Representation for Efficient Indoor Scene Reconstruction
- arXiv: https://arxiv.org/abs/2506.06988
- Uses textured meshes for suitable regions and Gaussians for complex geometry, jointly optimized for quality/FPS.
- Kill switch: “use mesh for some regions and Gaussians for others” is occupied.
- Maveb must investigate migration/selection over time and under explicit resource/update budgets, not a fixed hybrid.

### MeshGS
- arXiv: https://arxiv.org/abs/2410.08941
- Mesh-aligned Gaussians with different roles relative to reconstructed mesh geometry.
- Further blocks naïve mesh+Gaussian novelty.

### EliGSiR: Continual RGB-D Mapping with Gaussian Splatting under Bounded Compute
- arXiv: https://arxiv.org/abs/2609.20348
- Posted 2026-09-17.
- Evidence-guided, load-adaptive continual RGB-D Gaussian mapping with view scheduling, adaptive supervision fidelity and targeted geometry growth.
- Kill switch: H6 cannot be a generic bounded-compute/evidence-guided 3DGS scheduler.
- Required response: use EliGSiR as a direct baseline/collision for any compute-budget work and move Maveb's core question toward heterogeneous representation/dependency scheduling if evidence supports it.

### Mobile-GS
- arXiv: https://arxiv.org/abs/2603.11531
- Mobile real-time rendering, order-independent rendering and compression/pruning.
- Blocks broad “mobile Gaussian efficiency” novelty.

### Matryoshka Gaussian Splatting
- arXiv: https://arxiv.org/abs/2603.19234
- Continuous LOD through an ordered Gaussian prefix with stochastic budget training.
- Any quality-vs-budget Gaussian-only scheme must account for this.

## Current research pivot

The strongest Maveb-specific conjunction to falsify next is:

> A persistent captured world can minimize recomputation by carrying explicit evidence and stable regional identity through a heterogeneous representation graph, allowing regions to migrate among volumetric, mesh and Gaussian forms under changing evidence and bounded resources.

This is a hypothesis, not a novelty claim.

The next cheap probes should separate its components:

1. Measure the current association baseline's identity survival / switch regime on controlled revisions.
2. Measure the exact fraction of Gaussian primitives and dirty spatial regions touched by current selective updates.
3. Build an offline oracle for per-region mesh-vs-Gaussian choice from measured residual, memory and cost.
4. Simulate representation migration from logged per-region costs before implementing online migration.
5. Compare dependency-closure work against Gaussian-only local update, CL-Splats-style locality proxy, and full rebuild.
6. Refresh literature before promoting any survivor.
