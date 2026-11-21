# Teaching source map — Maveb

> A guided source-reading itinerary. It is not a test result or claim that every file is documented yet.

## How to use this guide

Study the scientific question first, then the certificate mathematics, then representation-specific implementations and finally frozen evidence. AETHER is the systems stack; MAVEB/CBRC is the research contribution.

Read each phase in order. Every link goes to a source file or directory in this repository. For a directory, inspect its public interface and then its implementation files. After each phase, identify the caller, the state it owns, the inputs it validates, and its observable outputs.

## 1. Problem and evidence

1. [`README.md`](README.md)
2. [`research/results/CBRC_PAPER_GRADE_EVIDENCE_2026-09-24.md`](research/results/CBRC_PAPER_GRADE_EVIDENCE_2026-09-24.md)
3. [`research/results/CBRC_CLAIM_LEDGER_2026-09-24.md`](research/results/CBRC_CLAIM_LEDGER_2026-09-24.md)
4. [`research/results/CBRC_EXPERIMENT_RUNBOOK.md`](research/results/CBRC_EXPERIMENT_RUNBOOK.md)

## 2. Build and system entry

1. [`CMakeLists.txt`](CMakeLists.txt)
2. [`CMakePresets.json`](CMakePresets.json)
3. [`bootstrap_and_run.sh`](bootstrap_and_run.sh)
4. [`run_all.sh`](run_all.sh)

## 3. Implementation directories

1. [`engine/core`](engine/core)
2. [`engine/scene`](engine/scene)
3. [`engine/world`](engine/world)
4. [`engine/revision`](engine/revision)
5. [`engine/cbrc`](engine/cbrc)
6. [`engine/gaussian`](engine/gaussian)
7. [`engine/world_gaussian`](engine/world_gaussian)
8. [`engine/reconstruction`](engine/reconstruction)
9. [`engine/mesh`](engine/mesh)
10. [`engine/metal`](engine/metal)
11. [`engine/rendergraph`](engine/rendergraph)

## 4. Verification and reproducibility

1. [`tests/RevisionPlannerTests.cpp`](tests/RevisionPlannerTests.cpp)
2. [`tests/GaussianLocalityCertificateTests.cpp`](tests/GaussianLocalityCertificateTests.cpp)
3. [`tests/GaussianImageRevisionCertificateTests.cpp`](tests/GaussianImageRevisionCertificateTests.cpp)
4. [`tests/OracleGeometryTests.cpp`](tests/OracleGeometryTests.cpp)
5. [`tests/TemporalRevisionCertificateTests.cpp`](tests/TemporalRevisionCertificateTests.cpp)
6. [`tests/SparseTsdfTests.cpp`](tests/SparseTsdfTests.cpp)
7. [`run_reviewer_stress_campaign.sh`](run_reviewer_stress_campaign.sh)
8. [`researchpaper`](researchpaper)

## End-to-end interaction map

Capture creates a persistent world representation; edits change owned world/representation state; revision planning computes dependency closure and conservative exterior bounds; CBRC chooses certified LOCAL work or FULL fallback; Gaussian/TSDF/mesh backends update and publish; tests compare selected revisions with an independent full recomputation oracle.

## APIs and code-reading questions

For each function, distinguish **contract** (preconditions, postconditions, failure modes), **implementation** (state/algorithms), **collaborators** (imports, calls and consumers), **lifetime/ownership**, and **verification** (test or evidence that checks it). For C++ modules, `export module` names the public compiled interface and `import` expresses module dependencies; an implementation unit's `module ...;` contributes definitions without exporting them.

## Boundaries and honesty

Frozen headline work reduction is **calibrated work**, not paired wall-clock speedup. An absence of observed certificate violations is not universal proof. Preserve frozen evidence and manuscript provenance.

## Documentation rules

- Teaching comments describe *why*, invariants, edge cases, API ownership and cross-file effects; avoid narrating obvious assignments.
- Preserve behavior during documentation-only edits; keep correctness changes in separate reviewed commits.
- Link function names and tests where possible; mark claims as source-present, CI-observed, host-verified or research-evidenced.
- License grants apply only to material for which the repository owner holds rights; third-party source, models, media and datasets keep their own notices.
