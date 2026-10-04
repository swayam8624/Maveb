# CBRC experiment runbook

This is the reproducible execution order for CBRC v1.

## 0. Canonical paper-grade path

For the current v1 paper line, the preferred top-level command is:

```bash
./run_paper_grade_research.sh
```

It executes the public v2.1 RGB/SfM campaign, the pinned trained-3DGS
validation, the mechanism-isolation ablation stress suite, the
cross-representation comparison artifact, and the final readiness audit.

The public v2.1 campaign enforces the production persistent-world effective
translation threshold before freezing cases. Sub-threshold requested edits are
recorded together with the applied minimum effective translation; they are not
silently passed to production as no-op edits.

The final reporting code treats certificate effectivity as **undefined** when
the independently measured residual is numerically zero. Do not manufacture a
large ratio by dividing by an arbitrary tiny denominator floor.

## 1. Verify the implementation

```bash
cmake --preset ci
cmake --build --preset ci
ctest --preset ci

cmake --preset sanitizer
cmake --build --preset sanitizer
ctest --test-dir build/sanitizer --output-on-failure

python3 -m unittest discover -s benchmarks/tests -p 'test_*.py'
python3 -m unittest discover -s research/tests -p 'test_*.py'
```

No experimental result is accepted while these gates are red.

## 2. Run theorem/reference falsification

Gaussian + temporal randomized chain:

```bash
python3 research/experiments/cbrc_gaussian_temporal_chain.py \
  --seed 20260920 \
  --trials 100000
```

The command exits non-zero on the first observed bound violation.

Synthetic pilot:

```bash
python3 research/experiments/cbrc_synthetic_benchmark.py \
  --out research/results/cbrc-synthetic-pilot.jsonl \
  --seed 20260920 \
  --repeats 1 \
  --pilot
```

The synthetic benchmark validates phase behavior only. It is not a real-world performance result.

## 3. Calibrate heterogeneous work

Collect isolated microbenchmark rows in JSONL. Each row must contain:

```json
{
  "domain": "gaussiansUpdated",
  "unit": "gaussians",
  "units": 10000,
  "elapsed_ms": 2.4,
  "baseline_ms": 0.1,
  "calibration_id": "machine-date-id"
}
```

Freeze coefficients:

```bash
python3 benchmarks/scripts/cbrc_calibrate_work.py \
  --input /absolute/path/calibration.jsonl \
  --version /machine/cbrc-v1 \
  --minimum-repeats 5 \
  --output /absolute/path/frozen-work-cost.json
```

Keep the raw calibration JSONL with the result archive.

## 4. Prepare real persistent worlds

Each campaign scene must have:

- persistent world archive;
- immutable Gaussian sidecar for the starting revision;
- immutable ownership sidecar for the same revision;
- entity IDs with Gaussian ownership;
- frozen camera parameters;
- monotonic revision timestamps.

Do not reuse one mutable archive across campaign cases unless sequential revisions are intentional. For paired method comparisons, copy the same starting archive and sidecars so all methods see identical before-state.

## 5. Freeze the campaign manifest

Start from:

`research/config/cbrc_real_campaign.example.json`

Before running final results, freeze:

- scene IDs;
- edit IDs;
- target transforms;
- camera;
- epsilon;
- coupling regime labels;
- work-cost model path;
- whether history validation is deliberately stable/unstable.

Do not retune epsilon after reading final results.

## 6. Run the campaign

```bash
python3 benchmarks/scripts/cbrc_campaign.py \
  --campaign /absolute/path/campaign.json \
  --oracle build/ci/tools/maveb-cbrc-gaussian-oracle/maveb-cbrc-gaussian-oracle \
  --revision-tool build/ci/tools/maveb-cbrc-revision/maveb-cbrc-revision \
  --git-sha "$(git rev-parse HEAD)" \
  --output-dir /absolute/path/results
```

The campaign itself performs capture, independent replay, baseline/ablation execution, planner parity, strict evaluation and paper-artifact generation.

A campaign exit code of 5 means an evidence gate failed even if individual commands executed.

## 7. Inspect safety before speed

First inspect:

1. `campaign-gates.json`
2. `campaign-evaluation.json`
3. `planner-parity.json`
4. all per-case `spatial-evidence.csv`

Stop immediately if any certified case has measured error above its bound.

Only after the safety gate passes should work/latency comparisons be interpreted.

## 8. Required baseline and ablation evidence

Baselines:

- FULL
- EXACT
- RADIUS_0
- RADIUS_1
- RADIUS_2
- RADIUS_3
- FRACTION
- EMPIRICAL
- CBRC

Ablations include:

- no predecessor closure;
- remove Gaussian analytic theorem;
- remove temporal analytic theorem;
- no QoI specialization;
- collapse hard/soft separation;
- global norm tail instead of graph-structured exterior;
- no fallback.

Dense Python vs sparse native planner agreement is enforced separately by `planner-parity.json`.

The frozen real campaign can be non-discriminative for some individual
ablations. Do not retune the real matrix after seeing that result. Instead run
the separately labeled synthetic mechanism-isolation suite:

```bash
python3 research/experiments/cbrc_ablation_stress_suite.py \
  --output build/paper-grade-final/ABLATION_STRESS_STATUS.json
```

This suite is allowed to demonstrate mechanism necessity under targeted stress,
but it must never be presented as real-world effect-size evidence.

## 9. Paper artifacts

The campaign generates F1-F8 sources automatically. They can also be regenerated:

```bash
python3 research/analysis/cbrc_paper_artifacts.py \
  --rows /absolute/path/results/campaign-rows.jsonl \
  --baselines /absolute/path/results/campaign-baselines.jsonl \
  --spatial /absolute/path/results/cases/CASE/spatial-evidence.csv \
  --output-dir /absolute/path/results/paper-artifacts
```

Do not manually transcribe numerical result tables when a machine-readable source exists.

For zero measured residual, the F5/effectivity source marks the ratio as
undefined and records the zero-residual count. Source-edit effectivity and
selected-repair effectivity are named separately.

## 10. Archive a result

A shareable result archive should contain:

- exact git SHA;
- compiler/runtime/hardware identification;
- frozen campaign manifest;
- frozen work-cost model;
- raw calibration rows;
- campaign rows;
- baseline/ablation rows;
- planner parity;
- oracle spatial maps;
- provenance hashes;
- generated paper tables/figures;
- any failed-case artifacts.

A certificate failure is preserved, not deleted.
