# Maveb Research Protocol: Metric Geometric Uncertainty v1

- Status: preregistered research protocol, implementation gate U0
- Branch family: `agent/metric-uncertainty-*`
- Primary representation under study: metric geometry + 3D Gaussian Splatting
- Primary question: **Can calibrated geometric uncertainty from heterogeneous consumer sensors improve sparse-view metric reconstruction without hiding geometry errors behind rendering quality?**

## 1. Research posture

Maveb already contains enough rendering and reconstruction machinery to ask a serious research
question. This protocol therefore freezes unrelated feature expansion. Editor polish, new PBR
features, relighting, cinematic tooling, extra glTF coverage, semantic features, and new UI work do
not count as progress on this track unless an experiment below requires them.

The goal is not to show that depth, LiDAR, or confidence can be inserted into a pipeline. The goal is
to determine **when a metric prior is trustworthy, whether predicted uncertainty is calibrated, and
whether using that uncertainty improves geometry under sparse and imperfect observations**.

A result is valid even when the proposed method loses. Negative results, failure regimes, and
counterexamples are first-class outputs.

## 2. Research questions

### RQ1 — Calibration

Can observable quantities available to Maveb predict metric reconstruction error well enough to be
used as an uncertainty estimate?

Observable quantities in v1 are:

- sensor/depth confidence;
- metric depth;
- camera-pose confidence;
- pose reprojection error;
- focal length;
- cross-sensor Sim(3) position residual;
- cross-sensor orientation residual.

### RQ2 — Sparse-view geometry

Does inverse-variance weighting from a calibrated uncertainty model improve surface accuracy,
completeness, F-score, and normal consistency relative to both RGB/SfM-only reconstruction and a
naive `sensor_confidence * pose_confidence` metric-depth baseline?

### RQ3 — Robustness

How does the advantage change as views, depth observations, alignment quality, and pose quality are
systematically degraded?

### RQ4 — Rendering/geometry tradeoff

Can geometry improve without a material regression in novel-view rendering quality, convergence
cost, or memory?

### RQ5 — Transfer

Do coefficients fitted on calibration scenes retain calibration and ranking ability on disjoint
public scenes and paired Sony+iPad captures?

## 3. Hypotheses

- **H1:** predicted metric sigma is positively associated with absolute geometric error on held-out
  scenes. Primary statistic: scene-level Pearson correlation between predicted sigma and absolute
  error; rank correlation may be added later but cannot replace the preregistered metric.
- **H2:** on sparse-view scenes, calibrated inverse-variance weighting improves median Chamfer and
  F-score relative to naive confidence weighting.
- **H3:** the improvement is largest in the 4/8/12-view regimes and declines as RGB coverage becomes
  dense.
- **H4:** deliberately corrupting confidence or alignment metadata removes or reverses the gain. If
  the method is unaffected, the claimed uncertainty signal is not causally useful.
- **H5:** any geometry improvement must not cost more than a 3% relative LPIPS regression on the
  same held-out views unless the geometry/rendering Pareto tradeoff is explicitly reported.

## 4. Uncertainty model v1

The first model is deliberately simple and auditable. It is a hypothesis prior, **not a calibrated
sensor model**.

For a metric observation at depth `z`, define component standard deviations:

```text
sigma_sensor = (a + b z^2) * (1 + k (1 - c_sensor))
sigma_pose   = p0 + p1 (1 - c_pose)
sigma_reproj = z * e_reproj / f
sigma_align_position = e_align_position
sigma_align_rotation = z * tan(e_align_rotation)
```

The v1 independence hypothesis combines them in quadrature:

```text
sigma_total^2 = sigma_sensor^2
              + sigma_pose^2
              + sigma_reproj^2
              + sigma_align_position^2
              + sigma_align_rotation^2
```

The research weight is derived only after sigma is computed:

```text
w = clamp((sigma_reference / sigma_total)^2, w_min, w_max)
```

This decomposition is intentionally exposed in every prediction so that each term can be ablated.
The independence assumption is also an ablation target; it must not silently become a claim.

### Parameter fitting rule

Parameters `a`, `b`, `k`, `p0`, `p1`, and `sigma_reference` may be fitted only on the calibration
split. Once the first held-out evaluation begins, coefficients are frozen under a versioned
experiment identifier. Tuning on evaluation scenes invalidates that run.

The checked-in defaults are starting priors used to exercise the experimental harness. They are not
paper numbers and must never be described as calibrated.

## 5. Methods and ablations

Every paper-facing experiment must include these rows:

| ID | Method | Purpose |
|---|---|---|
| B0 | RGB/SfM-only | no metric prior |
| B1 | naive metric depth | existing sensor confidence × pose confidence weighting |
| B2 | uniform metric depth | depth prior with all accepted samples weighted equally |
| U1 | uncertainty without alignment terms | tests sensor/pose/reprojection terms |
| U2 | uncertainty without sensor confidence | tests whether confidence is useful |
| U3 | uncertainty with shuffled confidence | causal negative control |
| U4 | full metric uncertainty v1 | proposed method |

When Gaussian training is integrated, the same initialization and optimizer settings must be used
across rows except for the explicitly ablated mechanism.

## 6. Datasets and split discipline

### Public calibration/evaluation

- ARKitScenes is the primary public metric RGB-D source because Maveb already converts its RGB,
  depth, confidence, intrinsics, and poses into the recorded-capture contract.
- Calibration requires at least three sequences.
- Held-out public evaluation requires at least five disjoint sequences before any general claim.
- The currently wired `arkitscenes-47333462` sequence is an engineering smoke/evidence scene, not a
  sufficient research sample by itself.

### RGB geometry controls

ETH3D and DTU remain geometry controls for RGB/SfM and sparse-view behavior. They are not presented as
native heterogeneous-sensor experiments unless a depth source and its provenance are explicitly
added.

### Paired Maveb capture

A real paired dataset will be captured with Sony RGB and iPad LiDAR/RGB. Minimum target: eight static
scenes spanning:

1. texture-rich planar geometry;
2. texture-poor walls;
3. thin structures;
4. foliage/fine geometry;
5. reflective or glossy surfaces;
6. mixed near/far depth;
7. repeated texture;
8. occlusion-heavy geometry.

Each scene must retain original sensor files, calibration identity, timestamps, alignment residuals,
and a capture manifest. Scenes cannot be selected after seeing the proposed method's outcome.

## 7. Controlled stress matrix

The first complete study uses:

- RGB views: 4, 8, 12, 24;
- depth dropout: 0%, 25%, 50%, 75%;
- injected translation alignment noise: 0, 10, 25, 50 mm;
- injected rotation alignment noise: 0, 1, 2, 5 degrees;
- confidence control: intact, constant, shuffled;
- seeds: 11, 23, 42.

Noise injection must be deterministic from the recorded seed and must produce a provenance record.

## 8. Metrics

### Geometry

Primary:

- accuracy mean / median / p95;
- completeness mean / median / p95;
- symmetric Chamfer;
- F-score at preregistered thresholds;
- normal angular error.

### Uncertainty calibration

- empirical RMSE versus predicted RMS sigma in equal-count uncertainty bins;
- expected calibration error in metres;
- Gaussian negative log likelihood;
- 1-sigma and 2-sigma empirical coverage;
- correlation between predicted sigma and absolute error;
- sharpness (RMS predicted sigma), reported so a trivially huge uncertainty cannot look calibrated.

### Rendering

When Gaussian training enters the experiment:

- PSNR;
- SSIM;
- LPIPS;
- convergence curve versus iteration and wall time.

### Systems

- training/fusion wall time;
- peak resident memory;
- Gaussian count;
- TSDF resident blocks/voxels where applicable.

## 9. Statistical protocol

The **scene**, not a pixel, point, or Gaussian, is the unit of evidence for paper-level comparisons.
Millions of pixels from one room do not become millions of independent samples.

For each method/view-count condition:

1. retain raw per-sample errors for calibration plots;
2. compute per-scene summaries;
3. run all three deterministic seeds when stochastic training is involved;
4. compare methods pairwise within the same scene;
5. report median paired change and a 95% bootstrap interval over scenes;
6. publish every scene result, including failures.

Bootstrap code must use a recorded seed. Any excluded scene requires a reason written before method
comparison.

## 10. Decision gates

### U0 — Measurement gate

Required before uncertainty affects production fusion:

- deterministic uncertainty predictor with decomposed terms;
- deterministic calibration evaluator;
- unit tests for monotonicity, malformed input, calibration error, coverage, and bootstrap
  reproducibility;
- JSON/Markdown reports carrying input hashes and experiment settings.

### U1 — Public calibration gate

- produce predicted sigma/error pairs from at least three ARKitScenes calibration sequences;
- fit v1 coefficients only on those sequences;
- freeze coefficients and record the fitting script/config.

### U2 — Held-out calibration gate

On at least five disjoint scenes:

- uncertainty must rank geometric difficulty positively;
- calibration ECE and coverage must be reported, not hidden behind a single scalar;
- confidence-shuffle negative control must degrade usefulness.

Failure does not block publication of a negative result, but it blocks using the model as a
production confidence claim.

### U3 — Fusion ablation gate

Only after U2:

- add opt-in inverse-variance weighting to the CPU TSDF oracle;
- keep B0/B1/B2 behavior bit-for-bit available;
- evaluate the full stress matrix before porting the weighting to Metal.

### U4 — Gaussian gate

Only after the geometry effect is understood:

- compare SfM initialization, naive metric initialization, and uncertainty-aware initialization;
- then isolate optimization weighting, pruning/densification, and geometric regularization as
  separate ablations.

No combined "everything on" result is accepted without component ablations.

## 11. Minimum claim threshold

A positive headline claim requires all of the following on held-out sparse-view scenes:

- at least 10% median relative Chamfer improvement of U4 over B1 at 8 views;
- paired 95% bootstrap interval for the improvement that does not cross zero;
- confidence-shuffle control performs materially worse than U4;
- no more than 3% relative LPIPS regression, or an explicit Pareto claim instead;
- all preregistered scenes reported.

These thresholds may be revised only in a new protocol version committed before the corresponding
held-out experiment.

## 12. Reproducibility contract

Every experiment artifact must record:

- Maveb git SHA;
- experiment schema/version;
- dataset and source hashes where licensing allows;
- scene ID;
- method/ablation ID;
- view count;
- perturbation parameters;
- seed;
- exact tool argv;
- raw metrics and generated report hashes.

Generated bulk results stay outside Git; compact evidence summaries and the protocol stay in Git.

## 13. Literature map

The protocol is deliberately positioned against work showing that sparse-view Gaussian geometry and
priors are active research problems rather than solved engineering details:

- Kerbl et al., *3D Gaussian Splatting for Real-Time Radiance Field Rendering*, SIGGRAPH 2023.
- Kheradmand et al., *3D Gaussian Splatting as Markov Chain Monte Carlo*, NeurIPS 2024.
- Foroutan et al., *Evaluating Alternatives to SFM Point Cloud Initialization for Gaussian
  Splatting*, 2024.
- Turkulainen et al., *DN-Splatter: Depth and Normal Priors for Gaussian Splatting and Meshing*,
  WACV 2025.
- Wu et al., *Sparse2DGS: Geometry-Prioritized Gaussian Splatting for Surface Reconstruction from
  Sparse Views*, CVPR 2025.
- Conti et al., *ToF-Splatting: Dense SLAM using Sparse Time-of-Flight Depth and Multi-Frame
  Integration*, ICCV 2025.
- Tan et al., *Uncertainty-Aware Normal-Guided Gaussian Splatting for Surface Reconstruction from
  Sparse Image Sequences*, 2025.
- Xiao et al., *In Depth We Trust: Reliable Monocular Depth Supervision for Gaussian Splatting*,
  2026.
- Govindarajan et al., *Radiant Foam: Real-Time Differentiable Ray Tracing*, ICCV 2025.
- Sharafeldin et al., *Semantic Foam: Unifying Spatial and Semantic Scene Decomposition*, CVPR 2026.

The proposed novelty is **not** "use depth with Gaussians" or "use uncertainty with Gaussians".
The target contribution is narrower: calibrated cross-sensor metric uncertainty, its causal value
under sparse observations, and a reproducible analysis of when it should or should not influence
geometry and Gaussian reconstruction.

## 14. Paper skeleton

1. Problem: sparse Gaussian reconstruction can render plausibly while geometry remains unreliable.
2. Observation: heterogeneous sensors expose different, measurable error signals.
3. Method: decomposed metric uncertainty with calibration and inverse-variance use.
4. Experimental protocol: public + paired capture, controlled sparsity/noise, negative controls.
5. Results: calibration first, geometry second, rendering/system tradeoffs third.
6. Ablations and counterexamples.
7. Limitations: independence assumptions, sensor-specific calibration, dynamic scenes, reflective
   geometry, and transfer beyond the measured sensor pair.

The implementation is successful only if this document can gradually turn into the methods and
experiments sections of a defensible paper rather than a list of repository features.
