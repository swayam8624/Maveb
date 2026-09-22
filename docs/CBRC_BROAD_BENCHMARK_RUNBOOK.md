# MAVEB broad CBRC benchmark runbook

This campaign is the broader evaluation track requested after external manuscript feedback. It is
deliberately separate from the frozen 2026-09-21 60-case headline campaign. The old evidence remains
historical evidence; this campaign asks whether the same CBRC contract survives much broader
representations and data sources.

## Scientific rules

1. Freeze the implementation commit before opening aggregate outcomes.
2. Use one work calibration for the selected cross-dataset run.
3. Do not retune epsilon, coupling templates, or CBRC thresholds per dataset.
4. Keep LOCAL, FULL, blocked, failed, and protocol-correction evidence.
5. Dataset coordinate/format conversion is allowed only when its provenance is explicit.
6. Do not call cross-dataset empirical success a universal proof.
7. The broad campaign freezes four same-cardinality authored edit families: **translation, rotation, uniform scale, and opacity/appearance**. Each uses the same independent image-certificate/oracle path. Removal and insertion remain capability-gated because they change Gaussian cardinality/ownership.

## Benchmark families

| Dataset | Role | Environment variable |
|---|---|---|
| GraphDECO pretrained 3DGS | primary photorealistic 3DGS; all 13 canonical scenes | `MAVEB_GRAPHDECO_PRETRAINED` |
| 3RScan | real longitudinal indoor change | `MAVEB_3RSCAN` |
| ScanNet++ | high-quality laser/DSLR/iPhone capture | `MAVEB_SCANNETPP` |
| ARKitScenes | commodity mobile RGB-D | `MAVEB_ARKITSCENES` |
| Bonn RGB-D Dynamic | dynamic/adversarial fallback stress | `MAVEB_BONN_RGBD` |
| existing public v2 | frozen historical reference | `MAVEB_PUBLIC_V2_RESULTS_DIR` |

Dataset bytes stay outside Git. Their upstream licenses/access terms remain independent from MAVEB's
source license.

## 1. Inspect the download plan

```bash
python3 benchmarks/scripts/cbrc_broad_benchmark.py download-plan \
  --output build/broad-benchmark/DOWNLOAD_PLAN.json
```

The GraphDECO pretrained archive has a direct official URL and can be fetched automatically from the
printed plan. 3RScan, ScanNet++, and ARKitScenes deliberately use their official access/download
flows; the harness does not bypass registration or license gates.

## 2. Set dataset roots

Example layout:

```bash
export MAVEB_DATA="$HOME/Datasets/MAVEB"

export MAVEB_GRAPHDECO_PRETRAINED="$MAVEB_DATA/graphdeco-pretrained/models"
export MAVEB_3RSCAN="$MAVEB_DATA/3RScan"
export MAVEB_SCANNETPP="$MAVEB_DATA/ScanNetpp"
export MAVEB_ARKITSCENES="$MAVEB_DATA/ARKitScenes"
export MAVEB_BONN_RGBD="$MAVEB_DATA/BonnRGBD"
```

The paths may live on an external SSD.

## 3. Validate imports before doing expensive work

All benchmark families:

```bash
python3 benchmarks/scripts/cbrc_broad_benchmark.py import \
  --dataset graphdeco-pretrained-3dgs \
  --dataset 3rscan \
  --dataset scannetpp \
  --dataset arkitscenes \
  --dataset bonn-rgbd-dynamic \
  --output build/broad-benchmark/import/BROAD_IMPORT.json
```

A selected dataset must be ready. Missing selected evidence fails instead of silently shrinking the
benchmark.

To start with a subset:

```bash
python3 benchmarks/scripts/cbrc_broad_benchmark.py import \
  --dataset graphdeco-pretrained-3dgs \
  --dataset scannetpp \
  --output build/broad-benchmark/import/BROAD_IMPORT.json
```

## 4. One-command execution

```bash
export MAVEB_BROAD_DATASETS="graphdeco-pretrained-3dgs,3rscan,scannetpp,arkitscenes,bonn-rgbd-dynamic"
export MAVEB_BROAD_RESULTS_DIR="$PWD/build/broad-benchmark"

bash run_broad_benchmark_campaign.sh
```

The runner:

1. validates/freeze-imports selected dataset assets;
2. builds the revision, oracle, work-benchmark, and trained-3DGS seeder tools;
3. prepares immutable persistent worlds;
4. freezes one machine-specific work calibration;
5. freezes the cross-dataset revision matrix before outcomes;
6. executes CBRC, FULL/reference oracle, method baselines, ablations, and planner parity;
7. computes selected-render versus FULL-after visual fidelity;
8. computes per-dataset distributions, Wilson intervals, bootstrap median-work confidence intervals,
   and paired baseline sign tests;
9. hashes the final evidence set.

Defaults are 15 frozen multi-edit cases per prepared world (cycled deterministically across translation, rotation, uniform scale, and opacity) and 5,000 statistical bootstrap
resamples. For a smoke pass:

```bash
export MAVEB_BROAD_CASES_PER_SCENE=3
export MAVEB_BROAD_BOOTSTRAP_ITERATIONS=500
bash run_broad_benchmark_campaign.sh
```

Do not use smoke numbers in the paper.

## Preparation semantics by dataset

### GraphDECO pretrained

The official trained `point_cloud.ply` is imported by
`maveb-seed-trained-3dgs-world`. SH coefficients, opacity, anisotropic scale, and rotation remain
part of the trained representation.

### ScanNet++

The supplied DSLR COLMAP sparse model is converted through
`cbrc_seed_colmap_world.py`; the laser mesh remains independent reference context. This path is not
described as trained 3DGS.

### 3RScan / ARKitScenes / Bonn

The first broad CBRC output-side campaign uses a deterministic RGB subset and COLMAP to make a
Gaussian persistent world. Original depth, pose, transform, and change metadata remain provenance
and independent benchmark context. The harness does not claim that those metric channels were used
to train the seeded Gaussian field.

For 3RScan, changed reference/rescan pairs are frozen from the official metadata before outcomes.
That pair annotation is retained while the broad multi-edit campaign uses the reference scan
as the output-side world.

## 5. Package compact evidence for Git

Never add `build/broad-benchmark/worlds`, source images, source PLYs, or downloaded datasets to Git.

```bash
python3 benchmarks/scripts/cbrc_package_broad_results.py \
  --results-root build/broad-benchmark \
  --output-dir research/results/broad-benchmark-latest
```

The packager removes absolute local paths and includes only compact JSON/JSONL/CSV/Markdown evidence
plus the representative visual-quality image.

Then:

```bash
git switch -c results/maveb-broad-benchmark
git add research/results/broad-benchmark-latest
git commit -m "research: add broad CBRC benchmark evidence"
git push -u origin results/maveb-broad-benchmark
```

Open a PR. Do not alter thresholds or delete failed cases before committing the evidence.

## Expected paper-facing outputs

- `campaign/campaign-rows.jsonl` — per-revision contract evidence.
- `campaign/campaign-gates.json` — strict safety/fallback gates.
- `campaign/campaign-baselines.jsonl` — paired baselines/ablations.
- `visual-quality/CBRC_VISUAL_QUALITY.json` — selected versus FULL-after render fidelity.
- `statistics/CROSS_DATASET_STATISTICS.json` — overall/per-dataset statistics.
- `statistics/dataset-summary.csv` — compact table source.
- `BROAD_CAMPAIGN_COMPLETE.json` — SHA-256 completion manifest.

Removal/insertion are intentionally not part of this campaign yet. They must gain explicit persistent identity, Gaussian cardinality/ownership mutation, rollback, and independent-oracle semantics before they can be admitted.
