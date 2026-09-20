# CBRC machine-readable schemas

These schemas document the stable v1 evidence/configuration contracts.

- `cbrc_native_certificate.schema.json` — deterministic C++ planner artifact.
- `cbrc_revision_row.schema.json` — evaluated per-revision row after oracle replay.
- `cbrc_work_cost_model.schema.json` — frozen heterogeneous scalar work model.
- `cbrc_real_campaign.schema.json` — real campaign manifest.

## Versioning policy

`schemaVersion` changes only for a breaking structural artifact change.

Representation/research semantics are versioned separately:

- **graph version/scope** identifies the dependency graph contract;
- **bound version** identifies the analytic theorem/bound implementation;
- **cost-model version** identifies the frozen scalar work calibration.

A schema-compatible artifact with a different graph/bound/cost version is not automatically
comparable. Preserve all version fields in result archives.

## Safety policy

Schemas describe shape; code performs semantic safety checks.

Examples of checks that remain runtime responsibilities include:

- hard/cone cardinality consistency;
- non-negative finite work/bounds;
- production/offline bound agreement;
- native/Python planner parity;
- `actual <= bound <= epsilon`;
- full-reference work greater than zero;
- exact revision/camera/sidecar provenance.

Do not treat JSON-schema validation alone as a CBRC certificate.
