# Maveb Research Protocol: Metric Geometric Uncertainty v1.1

- Status: preregistered before public evidence acquisition
- Branch family: `agent/metric-uncertainty-*`
- Primary representation under study: metric geometry + 3D Gaussian Splatting
- Primary question: **Can calibrated geometric uncertainty from heterogeneous consumer sensors improve sparse-view metric reconstruction without hiding geometry errors behind rendering quality?**
- Public evidence revision: **CA-1M/FARO ground truth**

## 1. Research posture

Maveb already contains enough rendering and reconstruction machinery to ask a serious question. This
track freezes unrelated feature expansion. Editor polish, new PBR features, relighting, cinematic
tooling, semantics, and unrelated glTF work are not research progress unless an experiment below
requires them.

The study does not ask whether depth or confidence can be inserted into a reconstruction pipeline.
It asks whether observable sensing/registration signals can be converted into a metric uncertainty
that is calibrated on disjoint data, survives causal negative controls, and improves geometry under
sparse or corrupted observations. Negative and null results remain valid outcomes.

## 2. Ground-truth correction before acquisition

The initial protocol proposed ARKitScenes mobile reconstruction meshes as the public reference. No
selected public scene was downloaded, fitted, or evaluated under that plan. Before outcome
inspection, the protocol was revised because a reference produced from the same mobile capture
family is not independent enough for calibrating onboard LiDAR error.

Public U1/U2 evidence therefore uses **CA-1M**. For each selected capture CA-1M provides:

- onboard ARKit LiDAR depth, 256x192 UInt16 millimetres;
- released per-depth confidence in [0, 1];
- a separate ARKit-depth intrinsic matrix;
- FARO laser-scanner rendered GT depth, 512x384 UInt16 millimetres;
- a separate GT-depth intrinsic matrix;
- a registered camera pose in laser-scanner space.

GT pixels with value zero are unregistered and are excluded. ARKit and GT depth pixels are matched
by calibrated camera ray using their released intrinsics; a fixed 2x resize is forbidden. The old
ARKitScenes mesh sampler remains an engineering smoke/orientation oracle only and cannot satisfy U1
or U2 evidence gates.

## 3. Research questions

### RQ1 — Calibration
Can observable quantities available before reconstruction predict metric depth/geometry error?

### RQ2 — Sparse-view geometry
Does calibrated inverse-variance weighting improve accuracy, completeness, F-score and Chamfer over
uniform depth and naive confidence weighting?

### RQ3 — Robustness
How does any advantage change under view sparsity, depth dropout, pose noise and cross-sensor
misalignment?

### RQ4 — Geometry/rendering tradeoff
Can geometry improve without an unacceptable regression in novel-view quality, convergence cost or
memory?

### RQ5 — Transfer
Do coefficients fitted on public calibration captures retain calibration/ranking ability on disjoint
public captures and later on paired Sony+iPad scenes?

## 4. Hypotheses

- **H1:** predicted metric sigma is positively associated with absolute held-out error.
- **H2:** calibrated inverse-variance weighting improves sparse-view geometry over naive confidence.
- **H3:** benefit is largest at 4/8/12 views and declines with dense RGB coverage.
- **H4:** within-scene confidence shuffling and controlled alignment corruption reduce the benefit;
  otherwise the claimed signal lacks causal evidence.
- **H5:** geometry improvement does not exceed a 3% relative LPIPS regression unless reported as an
  explicit Pareto tradeoff.

## 5. Uncertainty model v1

For an observation at metric depth `z`:

```text
sigma_sensor = (a + b z^2) * (1 + k (1 - c_sensor))
sigma_pose   = p0 + p1 (1 - c_pose)
sigma_reproj = z * e_reproj / f
sigma_align_position = e_align_position
sigma_align_rotation = z * tan(e_align_rotation)
```

The v1 independence hypothesis is:

```text
sigma_total^2 = sigma_sensor^2
              + sigma_pose^2
              + sigma_reproj^2
              + sigma_align_position^2
              + sigma_align_rotation^2
```

Only after calibration may a reconstruction ablation use:

```text
w = clamp((sigma_reference / sigma_total)^2, w_min, w_max)
```

CA-1M U1 fits **only** `a`, `b`, and `k`. Its registered public frames do not identify Maveb's future
Sony↔iPad alignment term, and fitting those parameters here would create unearned degrees of freedom.
Pose/alignment parameters remain frozen until a paired-sensor experiment can identify them.

## 6. Frozen public split

The evidence-eligible split is `benchmarks/experiments/metric-uncertainty-public-split-v1.json`,
revision 2. Membership was selected before any chosen tar archive was downloaded or any selected
metric was inspected.

Calibration, CA-1M train / ARKitScenes Training metadata, distinct visits:

- `ca1m-42444499` — visit 421065
- `ca1m-42444511` — visit 421063
- `ca1m-42444574` — visit 421062

Held-out, CA-1M val / ARKitScenes Validation metadata, distinct visits:

- `ca1m-45662921` — visit 468646
- `ca1m-45261179` — visit 466802
- `ca1m-47115543` — visit 470655
- `ca1m-45261143` — visit 466801
- `ca1m-45261615` — visit 467293

The previously wired `arkitscenes-47333462` remains smoke-only. Selected evidence scenes cannot be
silently replaced because they are difficult, sparse, partially invalid, or unfavorable. A
replacement requires a new explicit split revision and invalidates outcomes already inspected.

## 7. Methods and negative controls

| ID | Method | Purpose |
|---|---|---|
| B0 | RGB/SfM-only | no metric prior |
| B1 | naive metric depth | existing sensor-confidence × pose-confidence weighting |
| B2 | uniform metric depth | accepted depth with equal weight |
| U1 | sensor uncertainty | calibrated public sensor/depth terms |
| U2 | no sensor confidence | replace confidence by a constant |
| U3 | shuffled confidence | preserve each scene histogram but break sample association |
| U4 | full metric uncertainty | later includes identified pose/alignment terms |

A confidence-aware claim is unsupported if U1/U4 is indistinguishable from the within-scene shuffled
control.

## 8. Public U1/U2 procedure

1. Validate frozen video membership against Apple's CA-1M `data/train.txt` / `data/val.txt`.
2. Download only the eight selected CA-1M tar archives.
3. For every sampled ARKit-depth pixel, map its calibrated camera ray into the GT-depth image using
   the released source/target intrinsics.
4. Exclude invalid ARKit depth, out-of-bounds mapped rays and zero/unregistered FARO GT depth.
5. Emit signed error `e = z_arkit - z_faro`, confidence and all observable model inputs.
6. Fit only sensor terms on the three calibration captures with scene-balanced Gaussian NLL.
7. Freeze model config, input hash, split hash and code revision.
8. Run the frozen model once on the five held-out captures.
9. Evaluate intact, constant and deterministic within-scene shuffled confidence.
10. Report every selected scene and write failure analysis before any fusion weighting is enabled.

Pixels are measurement samples; **scene is the paper-level unit of evidence**.

## 9. Calibration metrics

Report per scene and aggregate:

- RMSE;
- Gaussian negative log likelihood;
- equal-count-bin calibration error;
- empirical 1-sigma and 2-sigma coverage;
- RMS predicted sigma (sharpness);
- Pearson correlation of predicted sigma with absolute error;
- calibration curves/bins;
- deterministic scene-bootstrap intervals.

A huge sigma that merely achieves coverage is not a successful model; sharpness and NLL prevent that
failure from being hidden.

## 10. Geometry stress matrix (U3)

Only after U2:

- RGB views: 4, 8, 12, 24;
- depth dropout: 0%, 25%, 50%, 75%;
- translation misalignment: 0, 10, 25, 50 mm;
- rotation misalignment: 0, 1, 2, 5 degrees;
- confidence: intact, constant, shuffled;
- stochastic seeds: 11, 23, 42.

Dense CPU TSDF is the first intervention target. Sparse CPU and Metal remain downstream replication
backends, not independent research contributions.

## 11. Gaussian gate (U4)

Only after the geometry effect is understood, isolate these one at a time:

1. uncertainty-aware initialization;
2. uncertainty-weighted optimization;
3. uncertainty-aware pruning;
4. uncertainty-aware densification;
5. geometric regularization.

Every experiment uses the same Gaussian optimizer and training budget except for the named
intervention. A combined “everything on” result without component ablations is not accepted.

Rendering metrics are PSNR, SSIM and LPIPS; geometry metrics include accuracy, completeness, Chamfer,
F-score and normal error; system metrics include wall time, peak memory and Gaussian/TSDF counts.

## 12. Paired Sony+iPad extension

After public sensor calibration, capture at least eight preregistered static scene classes spanning
texture-rich planes, texture-poor walls, thin structures, fine geometry, glossy/reflective surfaces,
mixed depth, repeated texture and occlusion-heavy geometry.

Raw files, timestamps, calibration identity and Sim(3) residuals are immutable evidence. The key
extension is whether cross-sensor alignment residual predicts downstream metric error. Deliberate
translation/rotation perturbations are mandatory causal controls.

## 13. Statistical protocol

- scene, not pixel, is the unit for paper-level comparisons;
- keep raw per-sample errors for calibration analysis;
- compute per-scene summaries;
- pair method comparisons within scene;
- use deterministic bootstrap over scenes with recorded seed;
- report every preregistered scene, including failures;
- do not tune after held-out results are inspected.

## 14. Positive-claim gate

A positive headline reconstruction claim requires all of:

- at least 10% median relative Chamfer improvement of U4 over B1 at 8 views;
- paired 95% scene-bootstrap interval excluding zero;
- shuffled confidence materially worse than the intact/full model;
- no more than 3% relative LPIPS regression, unless explicitly framed as a Pareto tradeoff;
- all preregistered scenes reported.

Threshold changes require a new protocol version committed **before** the corresponding held-out
experiment. Null/negative results remain publishable research outcomes and never authorize quiet
threshold changes.

## 15. Reproducibility contract

Every evidence artifact records Maveb git SHA, split revision/hash, source archive hashes, scene,
method/ablation, sampling parameters, perturbations, seed, exact argv, fitted-model hash and raw/report
hashes. Bulk licensed data remains external; compact derived numerical evidence and provenance may be
committed when licensing permits.

## 16. Literature/novelty rule

The contribution is not “depth-guided GS”, “sparse-view GS”, or “uncertainty-aware GS”; those are
established method classes. Maveb's narrower test is **externally measurable metric sensing and
registration uncertainty that is calibrated before intervention and validated causally on disjoint
scenes**. `docs/research/LITERATURE_POSITIONING.md` is the novelty ledger and must be refreshed before
U3 and again before U4.

## 17. Implementation gates

- **U0 — measurement:** predictor, evaluator, bootstrap, controls, provenance, synthetic end-to-end
  fixture.
- **U1 — calibration:** independent CA-1M/FARO error samples from three frozen calibration captures;
  fit sensor terms only and freeze coefficients/hashes.
- **U2 — held-out:** five frozen CA-1M validation captures, no retuning, intact/constant/shuffled
  controls, calibration curves and failure analysis.
- **U3 — fusion:** opt-in inverse-variance dense CPU TSDF ablation with B1/B2 preserved; full stress
  matrix before sparse/Metal ports.
- **U4 — Gaussian:** isolated initialization/optimization/densification/pruning/regularization
  ablations plus geometry/rendering Pareto analysis.

The project is successful when this protocol can become the methods and experiments sections of a
defensible paper, including the result if the central hypothesis is false.
