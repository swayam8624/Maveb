# MAVEB Repository Audit — Discovery Baseline

**Audit date:** 2026-09-20  
**Repository:** `swayam8624/Maveb`  
**Immutable main baseline:** `1d95c8f480fb2868d821fa107215311f1deab17c`  
**Research branch:** `research/maveb-discovery`

## Critical truth

The default branch is not the whole current research system. Two major unmerged branches exist:

- **PR #27** — `perf/heavy-scene-interaction`, 29 commits ahead of main. Responsive preview/adaptive Gaussian budget/spatial ordering/async renderer loading.
- **PR #28** — `feat/persistent-world-core-v1`, 138 commits ahead of main. Persistent world identity/history, Reality Diff, entity association, selective updates, semantic graph, Gaussian ownership/local update, Studio history/editor surfaces.

Therefore every later experiment must name its exact base SHA. No result may casually say "MAVEB supports X" when X exists only on an unmerged branch.

## Strong implemented foundations on main

Main already contains a serious research platform: C++23 core, SwiftUI AetherStudio, Metal 3 renderer, render graph, glTF PBR, lighting/IBL/shadows/temporal rendering, deterministic Gaussian PLY ingestion, anisotropic CPU Gaussian oracle, Metal Gaussian correctness path, stable tile/depth ordering, GPU IDs/debug attachments, reverse-Z hybrid proxy/Gaussian composition, canonical packages, native GLB output, COLMAP/Brush adapters, iPad RGB+LiDAR capture, deterministic dense and sparse TSDF paths, CPU/Metal TSDF agreement, dirty-region CPU meshing, immutable generation snapshots, and MavebBench.

## Open or bounded claims

Do **not** overstate these:

- Named-scene Gaussian performance exit gates remain open.
- Sparse Metal TSDF exists as a bounded correctness slice, but live GPU scheduling, throughput/soak evidence, persistence/eviction, and GPU-resident meshing remain open.
- Sony/COLMAP ↔ iPad metric alignment has deterministic software gates, but paired physical E3 evidence remains open.
- Production Gaussian rendering and relighting are explicitly not claimed.
- Public/full dataset breadth, complete ablations, and release-quality benchmark evidence remain incomplete.

## Frozen negative research result

The metric-uncertainty track is scientifically useful but is **not a positive efficacy claim**. The repository's own frozen result says sensor confidence predicts metric error, while the tested hand-designed transfers into TSDF weighting, support gating, Gaussian covariance enlargement, and confirmatory opacity/visibility did not robustly improve held-out downstream geometry.

This is now a **negative-results constraint**: do not retune the exposed confirmatory rooms to rescue the old claim.

## Immediate research implication

The strongest discovery leverage is not "build another Gaussian renderer." It is the combination of:

1. deterministic reconstruction/rendering oracles on main;
2. bounded Metal and TSDF implementations;
3. MavebBench and frozen negative-result discipline;
4. the unmerged persistent-world substrate in PR #28;
5. the responsive/quality-budget substrate in PR #27.

The discovery campaign will test mechanisms that contemporary continual-GS systems do not already settle, with falsification before expansion.
