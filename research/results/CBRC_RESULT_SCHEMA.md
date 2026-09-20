# CBRC result schema and paper-result gates

No numerical result in this file is a measured claim until produced by the benchmark pipeline.

## Per-revision row

Identity: `run_id`, `git_sha`, `scene_id`, `revision_id`, `seed`, `method`, `hardware`, `cold_or_warm`.

Revision descriptors: `edit_class`, `changed_fraction`, `source_extent`, `coupling_regime`, `qoi_profile`.

Certificate: `hard_closure_fraction`, `cone_fraction`, `stable`, `fallback_full`, `bound_<qoi>`, `epsilon_<qoi>`, `susceptibility`, `transient_amplification`.

Oracle: `actual_<qoi>`, `certificate_violation_<qoi>`, `tolerance_violation_<qoi>`, `effectivity_<qoi>`.

Work: `work_total`, `work_ratio_full`, `work_tsdf`, `work_mesh`, `work_gaussian`, `work_texture`, `work_gpu`, `work_history`, `bytes_published`, `peak_memory_bytes`.

Timing: `plan_ms`, `repair_cpu_ms`, `repair_gpu_ms`, `publish_ms`, `total_ms`, `full_reference_ms`.

## Non-negotiable correctness gate

For every result shown as certified:

`actual_<qoi> <= bound_<qoi> <= epsilon_<qoi>`

for every declared QoI.

One violation invalidates the current certificate implementation/assumptions until explained and fixed. Do not average violations away.

## Desired evidence pattern, not a promised result

A. Localized revisions: CBRC uses materially less work than FULL and exact Boolean closure while satisfying the certificate.

B. High-coupling revisions: CBRC expands substantially rather than pretending the edit is local.

C. Globally coupled/adversarial revisions: CBRC selects FULL before local repair becomes more expensive.

The strongest explanatory result would be that raw changed fraction alone poorly predicts work, while propagation diagnostics explain the crossover.

## Tables

T1: correctness and certificate tightness by scene/edit class.
T2: work and latency versus FULL/EXACT/RADIUS/FRACTION/EMPIRICAL.
T3: ablations.
T4: planner overhead and memory.
T5: failure/fallback taxonomy.

## Mandatory ablations

No hard/soft separation; no predecessor closure; global norm tail only vs exterior response; no QoI specialization; empirical ordering vs no empirical ordering; no fallback; fixed radius; remove Gaussian analytic bound; remove temporal analytic bound; dense reference vs sparse production planner.

## Acceptance-to-write gate

Begin paper prose when the implementation-complete gate in `research/design/CBRC_IMPLEMENTATION_EXECUTION.md` is satisfied. Results and Discussion remain placeholders until the frozen benchmark scripts produce machine-readable evidence.
