# Maveb Novelty Matrix — 2026-09-20 refresh

Status: working literature map. This is not a systematic-review completion claim and does not establish novelty.

| Work | What it can do | What it does not establish for Maveb's target | Maveb capability / candidate distinction to test |
|---|---|---|---|
| Dynamic 3D Gaussians (2023) | Persistent Gaussian elements through continuous dynamic motion; dense tracking | Does not by itself answer intermittent long-term recapture with births/deaths/reconstruction churn and heterogeneous representation | Test explicit identity survival, switches, births/deaths across world revisions and whether identity causally protects unchanged state |
| CL-Splats (2025) | Continual Gaussian updates with change detection, local optimization and prior-state recovery | Gaussian-local update is not the same as a cross-representation invalidation/dependency graph | Quantify minimum transitive update closure TSDF→mesh→Gaussian→render state |
| GaussianUpdate (2025) | Multi-stage continual Gaussian update; visibility-aware replay | Does not establish Maveb's provenance ledger or heterogeneous migration | Require evidence records to cause measurable preservation/update-locality gain |
| LTGS (CVPR 2026 Findings) | Sparse-view long-term chronology, object-level changes, reusable Gaussian templates | Does not establish arbitrary region representation migration among mesh/Gaussian/volumetric states | Use as collision for chronology/object identity; test migration rather than chronology alone |
| GaME (CVPR 2026) | Online evolving-scene Gaussian map with structural adaptation and stale keyframe removal | Primarily maintains a Gaussian representation; not evidence that heterogeneous dependency closure/migration is better | Compare long-term update quality and work fraction against GaME-compatible task settings |
| GS-DIFF (2026) | Primitive-space scene change detection; geometric vs appearance change; observability | Does not establish a persistent heterogeneous world state or minimal recomputation architecture | Use primitive-space change as direct collision/baseline; avoid claiming geometric/appearance separation |
| MeshGS (2024) | Mesh-aligned Gaussian hybrid rendering | Not an online representation-selection/migration policy for evolving captured worlds | Dynamic evidence-driven selection must beat fixed hybrid |
| Hybrid Mesh-Gaussian Representation (2025) | Region roles split across textured meshes and Gaussians for rendering efficiency | Static/fixed hybrid allocation is not continual migration under update cost | Offline oracle then online migration; report quality-time-memory-update Pareto frontier |
| EliGSiR (2026-09-17) | Bounded-compute continual RGB-D Gaussian mapping; evidence-guided scheduling and adaptive fidelity | Does not automatically cover heterogeneous TSDF/mesh/Gaussian job scheduling | H6 demoted; any scheduler claim must be specifically heterogeneous/dependency-aware and compared against EliGSiR concepts |
| Mobile-GS (2026) | Mobile-tailored fast Gaussian rendering and compression | Does not establish persistent-world updating or heterogeneous world-state migration | Apple-silicon work must show a persistent-world algorithmic advantage, not a port |
| Matryoshka Gaussian Splatting (2026) | Continuous Gaussian-only LOD / budget-fidelity trade-off | Does not choose representation type per region | Quality-per-byte H7 must be heterogeneous or continual to remain interesting |

## Immediate implications

- **Do not pursue as headline claims:** generic local 3DGS updates, generic long-term Gaussian chronology, persistent Gaussian identity by itself, primitive-space geometry-vs-appearance change, generic bounded-compute Gaussian scheduling, generic mesh+Gaussian hybrid rendering.
- **Keep alive as falsifiable candidates:** heterogeneous dependency-minimal updates; evidence-ledger causality; online region representation migration; continual quality/time/memory/update Pareto allocation; persistent identity specifically as an enabling mechanism for those outcomes; Apple unified-memory architecture only if it changes the algorithmic frontier.
- **Required next evidence:** controlled identity probe, update-locality instrumentation, offline representation oracle, migration simulator, then external baseline reproduction.

## Sources

- Dynamic 3D Gaussians: https://arxiv.org/abs/2308.09713
- CL-Splats: https://arxiv.org/abs/2506.21117
- GaussianUpdate: https://arxiv.org/abs/2508.08867
- LTGS: https://arxiv.org/abs/2510.09881
- GaME: https://openaccess.thecvf.com/content/CVPR2026/html/Yugay_Gaussian_Mapping_for_Evolving_Scenes_CVPR_2026_paper.html
- GS-DIFF: https://arxiv.org/abs/2605.07203
- MeshGS: https://arxiv.org/abs/2410.08941
- Hybrid Mesh-Gaussian Representation: https://arxiv.org/abs/2506.06988
- EliGSiR: https://arxiv.org/abs/2609.20348
- Mobile-GS: https://arxiv.org/abs/2603.11531
- Matryoshka Gaussian Splatting: https://arxiv.org/abs/2603.19234
