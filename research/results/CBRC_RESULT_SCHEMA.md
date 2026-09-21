# CBRC result schema and evidence gates

Status: v1 artifact contract.

No numerical value described here is a paper measurement until it is produced by the frozen
benchmark pipeline on the declared real scene/hardware.

## Artifact layers

CBRC deliberately preserves several artifacts instead of collapsing everything into one row.

### 1. Native planner certificate

Produced by the C++ planner serializer and, for headless revisions, written as:

`native-planner-certificate.json`

Schema:

`research/schema/cbrc_native_certificate.schema.json`

Key fields:

- graph/bound/cost-model versions;
- stable / passes / fullRebuild;
- reason;
- local work and independent FULL work;
- sorted cone and exterior node IDs/names;
- per-QoI bound, epsilon and pass result.

This is the planner-level artifact. It does not contain the independent oracle measurement.

### 2. Production revision evidence

Headless capture emits:

- `translation.json`
- `certificate.json`
- `native-planner-certificate.json`

Studio exposes the equivalent post-frame production evidence through its bridge.

The production certificate includes the exact reference camera, Gaussian current-image bound,
temporal validation/repair decision, GPU publication counters and temporal invalidation counters.

### 3. Replay manifest

`replay-manifest.json` binds one production revision to:

- immutable before/after state;
- input format;
- exact camera;
- epsilon;
- production certificate;
- output planner graph;
- work ledger;
- optional frozen work cost model;
- graph/bound versions.

### 4. Evaluated revision row

`revision-row.json` / `campaign-rows.jsonl`

Schema:

`research/schema/cbrc_revision_row.schema.json`

Current top-level fields include:

- `schemaVersion`
- `scene_id`
- `revision_id`
- `git_sha`
- `method`
- `execution_mode`
- `graph_scope`
- `selection_mode`
- `edit_class`
- `coupling_regime`
- `changed_fraction`
- `graph_version`
- `bound_version`
- `hard_closure_nodes`
- `repair_cone_nodes`
- `total_nodes`
- `fallback_full`
- `stable`
- `planner_work`
- `full_work`
- `work_cost_model_version`
- `work_cost_unit`
- `qois`
- `work_ledger`
- `spatial_evidence`
- `candidateDiagnostics`

For each QoI the evaluated row records:

- epsilon;
- certified bound;
- measured full-reference error.

Rejected local candidates are retained in `candidateDiagnostics` even when the selected execution
falls back to FULL.

### 5. Campaign aggregate

A successful campaign directory contains:

- `campaign-rows.jsonl`
- `campaign-baselines.jsonl`
- `campaign-gates.json`
- `campaign-evaluation.json`
- `baseline-summary.json`
- `planner-parity.json`
- `paper-artifacts/`

The campaign also retains every per-case evidence directory.

## Non-negotiable correctness gate

For every result shown as certified, for every declared QoI:

```
measured_full_reference_error <= certified_bound <= epsilon
```

One `actual > bound` observation invalidates the current certificate implementation/assumptions
until explained and fixed. Violations are never averaged away.

A local candidate with `bound > epsilon` is not a certificate violation. It is a principled
reason to select FULL.

## Work accounting

Raw `LocalityLedger` domains stay in native units.

Do not sum blocks, cells, Gaussians, bytes, pages and pixels directly.

When a scalar minimum-work comparison is required, every non-zero ledger domain must have a frozen,
versioned coefficient in a `WorkCostModel` using one common unit. The default research unit is
milliseconds.

Schema:

`research/schema/cbrc_work_cost_model.schema.json`

The cost model is calibrated from isolated pre-evaluation microbenchmarks and frozen before final
campaign results are inspected.

## Campaign manifest

Schema:

`research/schema/cbrc_real_campaign.schema.json`

A case may either:

1. request headless revision capture from a persistent archive; or
2. point to already-produced translation/certificate evidence.

Final paired comparisons should start from identical before-state.

## Required methods

- FULL
- EXACT
- RADIUS_0
- RADIUS_1
- RADIUS_2
- RADIUS_3
- FRACTION
- EMPIRICAL
- CBRC

Uncertified baselines are retained with their measured work/error tradeoff. They are not silently
removed.

## Required ablations / parity

The frozen suite includes:

- no predecessor closure;
- remove Gaussian analytic bound;
- remove temporal analytic bound;
- no QoI specialization;
- collapse HARD/ANALYTIC separation;
- global infinity-norm tail;
- no certified fallback.

Fixed-radius variants are explicit baselines.

Dense/reference Python versus sparse/native C++ agreement is enforced separately by
`planner-parity.json` and the campaign `nativePythonPlannerParity` gate.

## Mandatory paper artifacts

F1. measured error vs certified bound with y=x safety line.
F2. work ratio vs changed fraction.
F3. coupling regime vs repair-cone fraction.
F4. automatic local-to-FULL crossover.
F5. effectivity distribution.
F6. per-layer work ledger.
F7. repair-cone/support plus screen-space residual.
F8. adversarial/high-coupling fallback.

Method/ablation tables are generated as:

- `T1_method_case_results.csv`
- `T2_method_summary.csv`

## Evidence-complete gate

Implementation is already complete. Performance/result claims require:

- real captured persistent-world revisions;
- frozen real hardware cost coefficients;
- at least one certified local case;
- at least one high/adversarial FULL fallback;
- zero certificate violations;
- native/Python parity;
- reproducible machine-readable rows;
- final repeated statistics.

See `CBRC_EXPERIMENT_RUNBOOK.md`.
