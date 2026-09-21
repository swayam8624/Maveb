# Criticality-Bounded Revision Cones (CBRC)

CBRC is MAVEB's fail-closed revision planner for persistent captured worlds. It asks a concrete systems question:

> After a physical-world edit, what is the smallest repair cone we can execute while conservatively certifying that unrepaired state cannot change the declared output quantity of interest beyond tolerance?

The implementation is deliberately conservative. Structural identity/provenance dependencies are exact. Only implementation-backed finite-change upper bounds are allowed to remain soft.

## Problem

Captured worlds are heterogeneous and persistent. A local physical edit can change one object while the system still carries state in multiple coupled representations:

- observations and provenance;
- TSDF blocks;
- mesh ownership and topology;
- texture pages and materials;
- Gaussian primitives;
- GPU publication buffers;
- temporal history;
- final rendered outputs.

A full rebuild gives a strong reference but repeats unaffected work. Purely local heuristics can be cheaper but may miss hidden dependencies or long-range output effects.

CBRC targets the middle ground:

> **Execute less than a full rebuild only when the unrepaired exterior can be conservatively bounded for the requested quantity of interest.**

The method is allowed to decide that no useful local repair exists.

## Proposed research contribution

The proposed novelty is not generic graph closure or a generic matrix resolvent. Those ideas have prior art.

MAVEB's contribution is the end-to-end captured-world specialization:

1. **typed repair semantics** — exact structural dependencies and analytic finite-change bounds live in the same revision graph;
2. **QoI-specific certification** — the planner reasons about an explicit output tolerance rather than generic node change;
3. **fail-closed use of evidence** — empirical influence may schedule work but does not certify;
4. **heterogeneous work discipline** — blocks, Gaussians, bytes and pixels are never summed without a frozen unit conversion model;
5. **automatic FULL fallback** — locality is an outcome of the certificate, not an assumption;
6. **machine-auditable provenance** — graph, bounds, cost model, cone, camera and revision identity are serialized;
7. **independent oracle replay** — the production decision is tested against a separate full-reference path.

The novelty claim remains subject to literature review and peer review. This repository documents what is technically different; it does not use README language as evidence of uniqueness.

## Potential impact

If the real-scene campaign shows useful effectivity and work reduction, CBRC could support:

- persistent XR scenes that update after localized physical changes;
- digital twins that avoid unnecessary global recomputation;
- reconstruction systems with one invalidation policy across TSDF, mesh, texture, Gaussian and temporal state;
- performance optimizations that carry a machine-readable correctness argument;
- negative-result workflows where a failed bound becomes a reproducible regression rather than disappearing from evaluation.

These are potential impacts. Final performance claims remain gated on the frozen real-scene campaign.

## Architecture

The end-to-end v1 chain is:

```
physical revision
  -> exact structural/hard closure
  -> typed heterogeneous revision graph
  -> analytic frontier propagation where proven
  -> QoI certificate
  -> greedy feasible repair cone
  -> regional repair or FULL fallback
  -> atomic publication / temporal invalidation
  -> machine-readable certificate
  -> independent full-reference replay for evaluation
```

### Core source map

Production planner:

- `engine/revision/include/aether/revision/RevisionPlanner.hpp`
- `engine/revision/src/RevisionPlanner.cpp`
- `engine/revision/include/aether/revision/RevisionCertificateJson.hpp`
- `engine/revision/src/RevisionCertificateJson.cpp`

Captured-world adapter:

- `engine/cbrc/include/aether/cbrc/CapturedWorldRevisionGraph.hpp`
- `engine/cbrc/src/CapturedWorldRevisionGraph.cpp`

Layer certificates:

- `engine/world_gaussian/.../GaussianImageRevisionCertificate.*`
- `engine/scene/.../TemporalRevisionCertificate.*`
- `research/theory/cbrc_layer_bounds.md`

Persistent transaction/locality:

- `engine/world_gaussian/.../GaussianLocalUpdate.*`
- `engine/world_gaussian/.../GaussianOverlaySpatialIndex.*`
- `engine/world/.../LocalityLedger.*`

Live rendering:

- `engine/metal/src/Renderer.cpp`
- `engine/metal/src/GaussianPipeline.cpp`
- `engine/metal/src/GaussianPipelineUpdates.cpp`

Headless evidence:

- `tools/maveb-cbrc-revision`
- `tools/maveb-cbrc-gaussian-oracle`

Reference / experiment code:

- `research/cbrc/`
- `research/experiments/`
- `benchmarks/scripts/cbrc_*.py`

## Dependency classes

### HARD

Used when identity or structural correctness is discrete and must be repaired exactly. Examples include ownership, topology, provenance, publication record identity and unstable temporal validation.

### ANALYTIC

Allowed only when the edge carries a conservative non-negative finite-change gain and explicit bound provenance.

Current v1 analytic bounds:

1. Gaussian edited-set opacity/transmittance -> image RGB L-infinity.
2. Stable temporal blend/clamp propagation -> resolved image.

### EMPIRICAL

May influence scheduling experiments but cannot certify. For certificate closure it is treated as exact.

## Planner semantics

The native planner receives:

- nodes with calibrated scalar work cost;
- conservative per-node finite-change magnitude;
- typed edges;
- direct exterior source bounds;
- a caller-supplied domain hard closure;
- one or more weighted QoI contracts with epsilon.

It returns:

- repaired cone;
- unrepaired exterior;
- per-QoI bound;
- pass/fail;
- stability;
- local work;
- independently measured FULL work;
- whether FULL reference rebuild was selected.

The search is greedy and produces a certified feasible cone. It does **not** claim global combinatorial optimality.

Analytic cycles in the unrepaired exterior fail closed in v1. The search must repair enough nodes to break the cycle or choose FULL.

## Build and test

```bash
cmake --preset ci
cmake --build --preset ci
ctest --preset ci
```

Sanitizers:

```bash
cmake --preset sanitizer
cmake --build --preset sanitizer
ctest --test-dir build/sanitizer --output-on-failure
```

Important CBRC native tests include:

- `MavebRevisionPlannerTests`
- `MavebRevisionCertificateJsonTests`
- `MavebCapturedWorldRevisionGraphTests`
- `MavebHeadlessCBRCRevisionToolTests`
- `MavebGaussianImageRevisionCertificateTests`
- `MavebTemporalRevisionCertificateTests`
- `MavebLocalityLedgerTests`

## Headless revision capture

Build tools, then execute one persistent Gaussian revision:

```bash
build/ci/tools/maveb-cbrc-revision/maveb-cbrc-revision \
  --archive /absolute/path/world.aetherworld \
  --entity 42 \
  --target 0.05,0.0,0.0 \
  --timestamp 1000000001 \
  --output-dir /tmp/cbrc-case \
  --width 1280 --height 720 \
  --focal-x 900 --focal-y 900 \
  --center-x 640 --center-y 360 \
  --epsilon 0.01
```

The output directory contains:

- `translation.json` — persistent edit/locality evidence;
- `certificate.json` — production Gaussian/temporal planner evidence;
- `native-planner-certificate.json` — canonical C++ planner artifact.

The world archive also receives immutable Gaussian and ownership sidecars for the new revision.

## Full-reference oracle

```bash
build/ci/tools/maveb-cbrc-gaussian-oracle/maveb-cbrc-gaussian-oracle \
  --before before.bin \
  --after after.bin \
  --input-format aether-bin \
  --detect-changed \
  --width 1280 --height 720 \
  --focal-x 900 --focal-y 900 \
  --center-x 640 --center-y 360 \
  --epsilon 0.01 \
  --spatial-output spatial-evidence.csv
```

Exit codes:

- 0 — certificate holds and bound is inside epsilon;
- 3 — certificate holds but candidate local execution is outside epsilon; choose FULL;
- 4 — **certificate violation**; stop the experiment line and investigate;
- other — configuration/execution failure.

## Work accounting

Never add raw heterogeneous counters together.

`LocalityLedger` retains native units. A frozen `WorkCostModel` converts non-zero domains into one common cost unit, normally milliseconds.

Calibration must be performed before final evaluation:

```bash
python3 benchmarks/scripts/cbrc_calibrate_work.py \
  --input calibration.jsonl \
  --version m2pro-cbrc-v1 \
  --minimum-repeats 5 \
  --output frozen-work-cost.json
```

Do not fit cost coefficients on final CBRC outcome rows.

## Real campaign

Copy and edit:

`research/config/cbrc_real_campaign.example.json`

Then run:

```bash
python3 benchmarks/scripts/cbrc_campaign.py \
  --campaign /absolute/path/campaign.json \
  --oracle build/ci/tools/maveb-cbrc-gaussian-oracle/maveb-cbrc-gaussian-oracle \
  --revision-tool build/ci/tools/maveb-cbrc-revision/maveb-cbrc-revision \
  --git-sha "$(git rev-parse HEAD)" \
  --output-dir /absolute/path/cbrc-results
```

The campaign requires, by default:

- minimum revision count;
- minimum scene count;
- at least one certified local case;
- at least one automatic FULL fallback;
- at least one high/adversarial coupling case;
- zero certificate violations;
- native/Python planner parity.

## Campaign outputs

Top level:

- `campaign-rows.jsonl`
- `campaign-baselines.jsonl`
- `campaign-gates.json`
- `campaign-evaluation.json`
- `baseline-summary.json`
- `planner-parity.json`
- `paper-artifacts/`

Per case:

- captured translation/certificate evidence;
- replay manifest;
- full-reference row;
- per-pixel spatial evidence;
- baseline/ablation result;
- content-addressed provenance.

## Correctness rule

Every row presented as certified must satisfy, for every declared QoI:

```
measured_full_reference_error <= certified_bound <= epsilon
```

Any `actual > bound` invalidates the current certificate implementation or assumptions. Do not average it away.

## What v1 does not claim

CBRC v1 does not claim:

- a globally optimal minimum-work cone;
- that every revision remains local;
- that empirical sensitivities are certificates;
- that synthetic results demonstrate real speedup;
- that unsupported analytic cycles are safe;
- that current measurements establish universal guarantees.

See `research/design/CBRC_LIMITATIONS.md` and
`research/design/CBRC_IMPLEMENTATION_STATUS.md`.
