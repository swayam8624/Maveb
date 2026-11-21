# MAVEB / AETHER — guided source reading order

This is a learning path through an **existing research system**, not a new experimental claim. Start from the question "How much of a captured world can I update locally while guaranteeing an explicitly bounded effect on a requested output?" Then follow its data, certificate, renderer and benchmark boundaries. For all source paths (including scripts and tests), use the [complete linked source catalog](docs/SOURCE_CATALOG.md).

## Mental model: the system's four responsibilities

```text
Sensor / captured world → WorldTimeline, entity edits and revision graph
                                       |
                                       v
                            CBRC captured-world adapter
                                       |
                                       v
                    RevisionGraph + QoI certificate + work model
                            /                    \
                   certified LOCAL          conservative FULL
                            \                    /
                             v                  v
                      CPU/Metal Gaussian, mesh, TSDF, textures
                                       |
                                       v
                           rendering, temporal invalidation
                                       |
                                       v
                          independent FULL-after oracle
                                       |
                                       v
                 benchmark rows → frozen evidence → manuscript
```

The world layer describes **what changed**. The CBRC adapter describes **what depends on that change**. The planner decides **what work may be skipped under the declared output tolerance**. The graphics backend applies and renders it. Tests and comparison scripts check the claim. The paper's measured "calibrated work reduction" is not automatically wall-clock speedup.

## Phase 1 — understand the public question and state model

1. [`README.md`](README.md) — read the problem, conservative fallback, supported claims, and limitations before any code.
2. [`engine/world/include/aether/world/PersistentWorld.hpp`](engine/world/include/aether/world/PersistentWorld.hpp) — public model for snapshots, revision numbers and differences. Ask what is immutable and what gets validated.
3. [`engine/world/src/PersistentWorld.cpp`](engine/world/src/PersistentWorld.cpp) — read `WorldTimeline::append`, `snapshot`, `diff`, `latestDiff`; trace changed entities into the revision workflow. `DiffPolicy` thresholds represent a chosen notion of difference, not ground-truth photometric error.
4. [`engine/world/include/aether/world/WorldEdit.hpp`](engine/world/include/aether/world/WorldEdit.hpp) and [`engine/world/src/WorldEdit.cpp`](engine/world/src/WorldEdit.cpp) — edits and state transitions. Compare user-facing changes with the canonical versioned world.

## Phase 2 — learn the mathematical/locality decision

5. [`engine/revision/include/aether/revision/RevisionPlanner.hpp`](engine/revision/include/aether/revision/RevisionPlanner.hpp) — the primary planner API: graph nodes, dependency edges, quantity-of-interest tolerances, local-work model, and certificates. Inspect the contract before implementation.
6. [`engine/revision/src/RevisionPlanner.cpp`](engine/revision/src/RevisionPlanner.cpp) — `RevisionGraph::build` validates the graph; `closeExactPredecessors` closes hard dependencies; cone selection evaluates conservative residuals and work. Watch the fail-closed FULL fallback and distinguish sufficient local cones from global optimality.
7. [`engine/cbrc/include/aether/cbrc/CapturedWorldRevisionGraph.hpp`](engine/cbrc/include/aether/cbrc/CapturedWorldRevisionGraph.hpp) — captured-world-specific node, cost, representation and output-tolerance inputs.
8. [`engine/cbrc/src/CapturedWorldRevisionGraph.cpp`](engine/cbrc/src/CapturedWorldRevisionGraph.cpp) — creates a generic revision graph from captured-world work and influence estimates. Follow calls into `revision::RevisionGraph::build` and the cone selector. This adapter should not silently redefine the mathematical certificate.

## Phase 3 — follow changes into graphics representations

9. [`engine/world/src/SelectiveUpdate.cpp`](engine/world/src/SelectiveUpdate.cpp) — selectively apply changed-world regions.
10. [`engine/metal/include/aether/metal/Renderer.hpp`](engine/metal/include/aether/metal/Renderer.hpp) — public render/GPU lifecycle contract. Review the ownership and synchronization model rather than treating Metal as a stateless draw-call library.
11. [`engine/metal/src/RendererGaussianUpdates.cpp`](engine/metal/src/RendererGaussianUpdates.cpp) — validate and commit Gaussian translations through the GPU pipeline; propagate temporal invalidation. This is an *execution* boundary, not the proof of which edits were safe to omit.
12. [`engine/metal/src/RendererGaussianScene.cpp`](engine/metal/src/RendererGaussianScene.cpp) — Gaussian scene and rendering integration; review how the scene's data reaches the renderer and how a frame depends on it.

## Phase 4 — the GUI and native bridges

13. [`apps/AetherStudio/Sources/AetherStudioApp.swift`](apps/AetherStudio/Sources/AetherStudioApp.swift) — SwiftUI document/window entrypoint.
14. [`apps/AetherStudio/Sources/AetherProjectDocument.swift`](apps/AetherStudio/Sources/AetherProjectDocument.swift) — project and document ownership.
15. [`apps/AetherStudio/Sources/ContentView.swift`](apps/AetherStudio/Sources/ContentView.swift) — user-facing controls and workspaces.
16. [`apps/AetherStudio/Bridge/AetherWorldBridge.mm`](apps/AetherStudio/Bridge/AetherWorldBridge.mm) and [`apps/AetherStudio/Bridge/AetherViewportBridge.mm`](apps/AetherStudio/Bridge/AetherViewportBridge.mm) — Objective-C++ boundary from SwiftUI to C++/Metal. Ask which side owns resources and which side copies data.

## Phase 5 — benchmark evidence and independent checks

17. [`apps/AetherBenchmark/main.cpp`](apps/AetherBenchmark/main.cpp) — native benchmark driver: arguments, scene data, GPU context and measurement path.
18. [`benchmarks/scripts/cbrc_campaign.py`](benchmarks/scripts/cbrc_campaign.py), [`cbrc_broad_benchmark.py`](benchmarks/scripts/cbrc_broad_benchmark.py) and [`cbrc_evaluate.py`](benchmarks/scripts/cbrc_evaluate.py) — understand preparation, run orchestration, aggregation, and the distinction between calibrated work and elapsed time.
19. [`tests/RevisionPlannerTests.cpp`](tests/RevisionPlannerTests.cpp), [`tests/CapturedWorldRevisionGraphTests.cpp`](tests/CapturedWorldRevisionGraphTests.cpp), and [`tests/GaussianLocalUpdateTests.cpp`](tests/GaussianLocalUpdateTests.cpp) — verify graph invariants, locality, and updates.
20. [`research/results/CBRC_CLAIM_LEDGER_2026-09-24.md`](research/results/CBRC_CLAIM_LEDGER_2026-09-24.md) and [`researchpaper/main.tex`](researchpaper/main.tex) — close the loop from source and frozen evidence to what the paper can legitimately claim. The broad run measured 1,275 revisions, with 935 certified LOCAL and 340 FULL fallbacks. Do not claim universal error guarantees or wall-clock speedups from these counts.

## API concepts as you read

- **`Result<T>` / `std::expected`:** success-or-typed-error return contract; inspect the failure case instead of assuming callers can continue.
- **`RevisionGraph`:** explicit nodes/edges with validated constraints; the hard-predecessor closure prevents an invalid truncated dependency selection.
- **QoI / epsilon:** the output quantity and its allowed error; not equivalent to geometric distance, photorealism, or an optimization objective.
- **Certificate:** a conservative bound under model assumptions. A zero observed discrepancy on evaluated images is not a proof for arbitrary scenes.
- **`WorldTimeline`:** revision history and edit differences; separate from GPU resource lifetime and from ground-truth photo reconstruction.
- **Metal renderer:** resource/device/command lifetimes and temporal history; GPU publication is separate from planner-certified locality.
- **SwiftUI / Objective-C++ bridge:** SwiftUI owns documents and interaction; bridging code adapts those requests to C++ engine APIs.

For the rest of the implementation — every Python tool, C++ header/source, Metal shader and Swift file — use [SOURCE_CATALOG.md](docs/SOURCE_CATALOG.md). Follow the nearest public header first, then the corresponding implementation, its caller, and its tests.

## Licensing and research boundaries

Original software is already under [Apache-2.0](LICENSE); research material has separate terms recorded in [LICENSES.md](LICENSES.md), and dependencies/datasets in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Learning and further development are encouraged within these licenses. This guide does not replace the frozen evidence or imply that unrun reviewer campaigns succeeded.
