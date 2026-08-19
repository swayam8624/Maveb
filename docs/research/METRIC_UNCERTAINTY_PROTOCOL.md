# Maveb Research Protocol: Metric Geometric Uncertainty v1.3

- Status: calibration amendment frozen before any held-out sidecar acquisition or U2 sampling
- Branch family: `agent/metric-uncertainty-*`
- Primary representation under study: metric geometry + 3D Gaussian Splatting
- Primary question: **Can calibrated geometric uncertainty from heterogeneous consumer sensors improve sparse-view metric reconstruction without hiding geometry errors behind rendering quality?**
- Public evidence: **CA-1M/FARO ground truth + ARKitScenes raw confidence**

## 1. Research posture

Maveb freezes unrelated feature expansion for this track. The study asks whether observable sensing
signals can be converted into metric uncertainty that is calibrated on disjoint data, survives causal
negative controls, and later improves sparse reconstruction geometry. Null and negative outcomes are
valid results.

Pixels are measurement samples. **Scene is the paper-level unit of evidence.**

## 2. Public evidence source history

The initial public plan used ARKitScenes mobile meshes as reference. Before selected-scene metric
sampling, this was rejected because the reference was not independent enough from the mobile sensor
family. Public truth was upgraded to CA-1M, whose FARO laser-scanner rendered depth is independently
registered to the capture camera.

After the selected CA-1M calibration archives were acquired, inspection of the first tar showed that
the released archive contains ARKit depth, FARO GT depth and their intrinsics, but no confidence
member. Before any valid metric sample existed, confidence was therefore sourced from the original
ARKitScenes raw `confidence` asset for the identical video IDs.

A second pre-outcome correction was required when CA-1M depth and raw confidence were found to use
different image orientations. ARKitScenes raw `lowres_depth` is therefore used **only as an
orientation witness**: for each joined frame the discrete image transform that best matches CA-1M
ARKit depth is selected, then the identical transform is applied to confidence. The witness is not a
ground-truth target, not a fitted variable, and never replaces FARO depth.

The evidence-eligible split is `benchmarks/experiments/metric-uncertainty-public-split-v1.json`,
revision 4. Scene membership has remained unchanged since revision 2.

## 3. Frozen public split

Calibration, distinct visits:

- `ca1m-42444499` — visit 421065
- `ca1m-42444511` — visit 421063
- `ca1m-42444574` — visit 421062

Held-out, distinct visits:

- `ca1m-45662921` — visit 468646
- `ca1m-45261179` — visit 466802
- `ca1m-47115543` — visit 470655
- `ca1m-45261143` — visit 466801
- `ca1m-45261615` — visit 467293

Selected scenes cannot be silently replaced because they are difficult or unfavorable. Replacement
requires a new explicit split revision and invalidates any already inspected held-out outcome.

## 4. Public observation construction

For every sampled frame:

1. CA-1M supplies onboard ARKit LiDAR depth and independent FARO rendered GT depth.
2. ARKitScenes raw supplies confidence levels 0/1/2 and raw low-resolution depth.
3. CA-1M nanosecond timestamp is joined to the nearest same-video ARKitScenes timestamp under a
   frozen 20 ms tolerance; actual delta is recorded.
4. Raw low-resolution depth selects one of the eight discrete image symmetries by lowest valid-depth
   disagreement with CA-1M ARKit depth; that transform is applied to confidence.
5. ARKit and FARO pixels are matched by camera ray using their separate released intrinsics; fixed
   2x resizing is forbidden.
6. Invalid ARKit depth, out-of-bounds mapped rays and zero/unregistered FARO depth are excluded.
7. Raw confidence level and normalized `c_sensor = raw_level / 2` are both preserved.

No target-dependent residual filter is applied.

## 5. Uncertainty model

For metric depth `z`:

```text
sigma_sensor = (a + b z^2) * (1 + k (1 - c_sensor))
sigma_pose   = p0 + p1 (1 - c_pose)
sigma_reproj = z * e_reproj / f
sigma_align_position = e_align_position
sigma_align_rotation = z * tan(e_align_rotation)
```

Independent components combine in quadrature:

```text
sigma_total^2 = sigma_sensor^2
              + sigma_pose^2
              + sigma_reproj^2
              + sigma_align_position^2
              + sigma_align_rotation^2
```

Only `a`, `b`, and `k` are fitted on public U1. Pose/alignment terms remain frozen until paired data
can identify them. Reconstruction weighting remains gated until U2:

```text
w = clamp((sigma_reference / sigma_total)^2, w_min, w_max)
```

## 6. U1a — original single-Gaussian calibration result

U1a used the preregistered scene-balanced Gaussian negative log likelihood on the deterministic
calibration sample set:

- `ca1m-42444499`: 94,706 samples;
- `ca1m-42444511`: deterministic 100,000 of 142,176;
- `ca1m-42444574`: deterministic 100,000 of 218,811;
- total fitted samples: 294,706;
- stable SHA-256 ranking per scene, seed 42;
- six coordinate rounds;
- 48 golden-section iterations per coordinate;
- parameter bounds: `a ∈ [1e-5, 0.10]`, `b ∈ [0, 0.05]`, `k ∈ [0, 20]`.

U1a is **retained as a failed calibration model**, not overwritten. Its fit pushed both geometric
noise coefficients to their exact upper bounds (`a≈0.10 m`, `b≈0.05 m/m²`) and put a large fraction
of observations at the fixed `maximumSigmaMetres=0.25` cap.

Calibration-only diagnostic evidence showed why:

- median absolute error ≈ 8 mm;
- p95 absolute error ≈ 87 mm;
- p99 absolute error ≈ 661 mm;
- RMSE ≈ 191 mm;
- only ≈2.2% of samples exceed 25 cm, but rare errors extend past 1 m;
- raw confidence is strongly ordered in empirical error: level 0 median ≈98 mm, level 1 ≈27 mm,
  level 2 ≈8 mm.

This distribution is incompatible with a single Gaussian scale model: rare catastrophic residuals
force ordinary measurements to be assigned unrealistically large sigma. U1a therefore does **not**
authorize U2 or production weighting.

## 7. U1b amendment — fixed Student-t(3) calibration

Because the failure was identified using calibration data only and no held-out confidence/depth
sidecar has been acquired or sampled, the protocol is amended before U2.

U1b changes **only the residual likelihood** from Gaussian to a fixed Student-t distribution with
`ν=3`. The choice is frozen before U2 and `ν` is not fitted.

All other U1 choices remain exactly unchanged:

- same frozen scenes and visits;
- same 294,706 deterministic selected samples;
- same sample seed 42;
- same `a`, `b`, `k` model and parameter bounds;
- same six coordinate rounds and 48 golden-section iterations;
- same 0.25 m maximum predicted sigma;
- no sample trimming, clipping by residual, RANSAC, or target-dependent rejection.

For `ν>2`, Student-t likelihood scale is parameterized so `sigma_total` remains the predictive
standard deviation:

```text
student_t_scale = sigma_total * sqrt((nu - 2) / nu)
```

Thus downstream inverse-variance weighting retains the original meaning if U2 later validates it.

U1b passes the calibration gate only if:

1. `a` and `b` do not both remain pinned to their upper search bounds;
2. the fitted model materially improves scene-balanced Student-t NLL over the initial config;
3. confidence is not silently credited merely because low-confidence points are heavy-tailed;
4. per-scene diagnostics are reported before U2;
5. the fitted U1b config, calibration input hash, split hash and code revision are frozen.

Failure of U1b is a valid negative result and blocks U2 intervention claims until the measurement
model is reformulated explicitly.

## 8. Research questions and hypotheses

### RQ1 — Calibration
Can observable quantities available before reconstruction predict metric error on disjoint scenes?

### RQ2 — Sparse-view geometry
Does validated inverse-variance weighting improve accuracy, completeness, F-score and Chamfer over
uniform depth and naive confidence weighting?

### RQ3 — Robustness
How does any advantage change under view sparsity, depth dropout, pose noise and cross-sensor
misalignment?

### RQ4 — Geometry/rendering tradeoff
Can geometry improve without an unacceptable novel-view regression?

### RQ5 — Transfer
Do public coefficients retain calibration/ranking ability on disjoint public captures and later on
paired Sony+iPad scenes?

Hypotheses:

- **H1:** predicted sigma is positively associated with absolute held-out error.
- **H2:** calibrated inverse-variance weighting improves sparse-view geometry over naive confidence.
- **H3:** benefit is largest at 4/8/12 views and declines with dense RGB coverage.
- **H4:** within-scene confidence shuffling and controlled alignment corruption reduce the benefit.
- **H5:** geometry improvement does not exceed a 3% relative LPIPS regression unless reported as a
  Pareto tradeoff.

## 9. U2 held-out procedure

U2 remains locked until U1b passes and its model hash is frozen. The legal order is:

```text
prepare-calibration -> Gaussian U1a diagnostic -> Student-t U1b -> freeze -> prepare-held-out -> evaluate
```

Only after U1b freeze may the five Validation confidence + orientation-witness sidecars be acquired.
U2 then evaluates the frozen model once on all five scenes with:

- intact confidence;
- constant confidence;
- deterministic within-scene shuffled confidence.

No coefficient, likelihood choice, confidence normalization, timestamp tolerance, image transform,
or scene membership may change after held-out outcomes are inspected.

## 10. U2 calibration metrics

Report per scene and aggregate:

- MAE, RMSE and robust error quantiles;
- Student-t(3) NLL for the amended model;
- Gaussian NLL as a descriptive legacy metric only;
- empirical coverage and sharpness;
- Pearson sigma↔|error| correlation;
- equal-count calibration curves/bins;
- raw confidence-level error strata;
- timestamp join coverage/deltas;
- orientation-witness transform counts/disagreement;
- deterministic paired bootstrap over scenes.

A large sigma that merely achieves coverage is not success. Ranking, sharpness, held-out likelihood,
and negative controls must agree.

## 11. Geometry stress matrix (U3)

Only after U2:

- RGB views: 4, 8, 12, 24;
- depth dropout: 0%, 25%, 50%, 75%;
- translation misalignment: 0, 10, 25, 50 mm;
- rotation misalignment: 0, 1, 2, 5 degrees;
- confidence: intact, constant, shuffled;
- stochastic seeds: 11, 23, 42.

Dense CPU TSDF is the first intervention target. Sparse CPU and Metal are downstream replication
backends, not independent contributions.

## 12. Gaussian gate (U4)

Only after the geometry effect is understood, isolate one at a time:

1. uncertainty-aware initialization;
2. uncertainty-weighted optimization;
3. uncertainty-aware pruning;
4. uncertainty-aware densification;
5. geometric regularization.

Rendering metrics: PSNR, SSIM, LPIPS. Geometry metrics: accuracy, completeness, Chamfer, F-score,
normal error. System metrics: wall time, peak memory and representation counts.

## 13. Paired Sony+iPad extension

After public calibration, preregister at least eight static scene classes spanning texture-rich and
texture-poor planes, thin structures, fine geometry, reflective surfaces, mixed depth, repeated
texture and heavy occlusion. Raw files, timestamps, calibration identity and Sim(3) residuals are
immutable evidence. Deliberate translation/rotation perturbations are mandatory controls.

## 14. Statistical protocol

- scene is the paper-level comparison unit;
- raw per-sample errors are retained for calibration diagnostics;
- comparisons are paired within scene;
- deterministic bootstrap over scenes uses recorded seed;
- every preregistered scene is reported, including failures;
- no tuning after held-out outcomes are inspected.

## 15. Positive-claim gate

A positive headline reconstruction claim requires all of:

- at least 10% median relative Chamfer improvement over naive confidence at 8 views;
- paired 95% scene-bootstrap interval excluding zero;
- shuffled confidence materially worse than intact uncertainty;
- no more than 3% relative LPIPS regression unless framed explicitly as a Pareto tradeoff;
- all preregistered scenes reported.

Null and negative results never authorize quiet threshold changes.

## 16. Reproducibility contract

Every evidence artifact records code SHA, split revision/hash, CA-1M archive hash, ARKitScenes
confidence and lowres-depth witness manifests, timestamp tolerance/deltas, orientation transforms,
scene, method, sampling parameters, seed, exact argv, fitted-model hash and report/raw hashes.

## 17. Literature/novelty rule

The contribution is not “depth-guided GS”, “sparse-view GS”, or “uncertainty-aware GS”. The narrower
claim under test is **externally measurable metric sensing/registration uncertainty, calibrated before
intervention and validated causally on disjoint scenes**. The literature ledger must be refreshed
before U3 and again before U4.

## 18. Implementation gates

- **U0 — measurement:** predictor, evaluator, provenance, controls and synthetic fixtures.
- **U1a — Gaussian calibration:** completed and recorded as a failed heavy-tail model.
- **U1b — robust calibration:** fixed Student-t(3), same samples/terms/bounds, no trimming; must pass
  before U2 is unlocked.
- **U2 — held-out:** five frozen validation captures, no retuning, intact/constant/shuffled controls.
- **U3 — fusion:** opt-in dense CPU inverse-variance ablation with naive/uniform baselines.
- **U4 — Gaussian:** isolated initialization/optimization/densification/pruning/regularization
  ablations plus geometry/rendering Pareto analysis.

The project is successful when this protocol can become defensible methods and experiments sections,
including a publishable negative result if the central hypothesis is false.
