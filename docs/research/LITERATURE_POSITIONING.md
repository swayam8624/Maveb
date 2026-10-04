# Literature Positioning: Metric Uncertainty and Sparse Gaussian Reconstruction

- Research track: `metric-uncertainty-v1`
- Purpose: prevent novelty drift and define experiments that distinguish Maveb from adjacent work.
- Rule: this is a positioning ledger, not a citation dump. Every added paper must change either a
  baseline, an ablation, a metric, or the claimed scope.

## 1. The narrow gap Maveb is testing

The literature already establishes all of the following separately:

1. 3D Gaussian Splatting is sensitive to initialization and densification choices.
2. Sparse-view Gaussian reconstruction is ill-posed and can overfit or produce weak geometry.
3. Depth, normal, MVS, semantic, and sparse active-depth priors can improve sparse reconstruction.
4. Uncertainty can be modeled inside Gaussian reconstruction.
5. Explicit spatial structures can make learned scene representations easier to ray trace or
   interact with.

Therefore **none** of those statements is a defensible novelty claim for Maveb.

Maveb instead tests a narrower question:

> Given heterogeneous consumer sensors with metric but imperfect geometry, can observable sensor,
> pose, reprojection, and cross-sensor alignment errors be converted into a *calibrated metric
> uncertainty*, and does that uncertainty have causal value for sparse geometry and Gaussian
> reconstruction beyond naive confidence weighting?

The contribution succeeds only if calibration is measured on held-out scenes and shuffled/constant
confidence controls demonstrate that the uncertainty signal is actually informative.

## 2. Positioning matrix

| Work | Main problem | Prior / representation | What it establishes | What Maveb must do differently |
|---|---|---|---|---|
| Kerbl et al., **3D Gaussian Splatting**, SIGGRAPH 2023 | real-time radiance-field rendering | SfM-initialized anisotropic Gaussians | foundational rasterized 3DGS representation | baseline only; no novelty claim around basic Gaussian rendering |
| Kheradmand et al., **3D Gaussian Splatting as Markov Chain Monte Carlo**, NeurIPS 2024, arXiv:2404.09591 | heuristic densification / initialization sensitivity | probabilistic interpretation of Gaussian population; SGLD-style updates | reframes cloning/splitting and improves robustness to initialization | keep MCMC-style training as a later optimizer baseline; uncertainty here must mean *measured metric geometric uncertainty*, not Gaussian population stochasticity |
| Foroutan et al., **Evaluating Alternatives to SFM Point Cloud Initialization for Gaussian Splatting**, 2024, arXiv:2404.12547 | dependence on SfM point initialization | random and NeRF-derived initialization | careful initialization can match or beat SfM in some settings | U4 must compare against strong non-metric initialization baselines; “better initialization” alone is insufficient |
| Jung et al., **RAIN-GS**, 2024, arXiv:2403.09413 | inaccurate / random initialization | optimization modifications | relaxes dependence on accurate SfM initialization | metric uncertainty must show benefit beyond optimizer robustness to initialization |
| Turkulainen et al., **DN-Splatter**, WACV 2025 | weak indoor Gaussian geometry | depth + normal regularization, smoothness | geometric cues improve indoor reconstruction and meshing | “use depth” and “use normals” are prior art; Maveb must test calibrated trust in metric observations and sensor failure regimes |
| Wu et al., **Sparse2DGS**, CVPR 2025 | sparse-view surface reconstruction | MVS initialization + geometry-prioritized enhancement | strong geometry gains from dense MVS priors under sparse input | include a dense-prior baseline when feasible; Maveb's distinction is heterogeneous metric sensing + calibrated uncertainty + causal controls |
| Park et al., **DropGaussian**, CVPR 2025 | sparse-view overfitting | prior-free stochastic Gaussian dropping | sparse-view rendering can improve without an external geometric prior | useful counterpoint: improvements under sparsity cannot automatically be attributed to metric geometry; compare rendering/geometry separately |
| Tang et al., **SPARS3R**, CVPR 2025 | sparse reconstruction from dense depth priors with pose/alignment issues | SfM pose + dense depth + global/local alignment | alignment quality is a first-order issue when importing dense priors | Maveb must treat cross-sensor alignment residual as an uncertainty variable rather than assuming alignment is solved after Sim(3) |
| Conti et al., **ToF-Splatting**, ICCV 2025 | dense SLAM with extremely sparse active depth | sparse ToF + RGB + multiframe geometry | sparse active depth can materially aid Gaussian SLAM | Maveb must distinguish its consumer LiDAR/Sony setting through calibrated uncertainty, held-out transfer, and controlled alignment corruption |
| Tan et al., **UNG-GS**, 2025, arXiv:2503.11172 | sparse-sequence geometric uncertainty | learned spatial uncertainty field + normal guidance | uncertainty-aware Gaussian geometry is already an active method class | “uncertainty-aware GS” is not novel; Maveb must focus on externally measurable metric uncertainty, calibration, and sensor-causal validation |
| Han et al., **high-confidence depth propagation with normal priors**, 2026, arXiv:2607.03765 | sparse-view surface reconstruction | confidence-guided depth propagation + normals | high-confidence regions can propagate geometry constraints | a confidence mask/propagation claim is insufficient; Maveb asks whether confidence is *calibrated to metric error* and when it should reduce influence |
| Govindarajan et al., **Radiant Foam**, ICCV 2025 | limitations of rasterized learned scene representations for ray effects | radiance on a volumetric mesh / ray tracing | explicit spatial structure can retain neural rendering quality and support ray-based graphics | future Maveb hybrid work should compare representation affordances, not claim that adding a proxy mesh alone solves interaction/relighting |
| Sharafeldin et al., **Semantic Foam**, CVPR 2026 | interaction / semantic decomposition of learned scenes | explicit Foam cells + semantic field | spatial structure improves consistency and interaction | future semantics belongs after the uncertainty study; it is not part of metric-uncertainty v1 |

## 3. Baselines implied by the literature

The study is under-baselined if it contains only vanilla 3DGS and Maveb's full method. At minimum,
results should distinguish:

- SfM-only 3DGS;
- strong sparse-view/prior-free Gaussian regularization where reproducible;
- naive metric depth/confidence weighting;
- uniform accepted metric depth;
- depth-prior Gaussian regularization comparable in spirit to DN-Splatter;
- a dense geometric-prior initialization baseline when dataset/tooling permits;
- Maveb uncertainty with each component removed;
- constant and shuffled confidence controls.

If computational budget prevents a literature baseline from being run, the paper must say so rather
than silently selecting weak comparators.

## 4. What “uncertainty” means here

Maveb uses three deliberately separated concepts:

### 4.1 Observational uncertainty

A predicted metric standard deviation derived from observable quantities before the reconstruction
method sees ground truth. This is the object being calibrated.

### 4.2 Epistemic / optimization uncertainty

Uncertainty arising from sparse views, weak constraints, Gaussian optimization, or a learned
uncertainty field. Related work already studies this. It is not interchangeable with sensor error.

### 4.3 Empirical error

The signed or absolute metric discrepancy against held-out reference geometry. This is evaluation
truth and may never be fed back into the predictor on held-out scenes.

Conflating these three would invalidate the main claim.

## 5. Experiments required to distinguish Maveb

### E-A — Does the confidence signal contain information?

Within each held-out scene, compare intact confidence with a constant value and a deterministic
within-scene shuffle that preserves the exact confidence histogram. If shuffled confidence performs
similarly, sample-level confidence carries little causal information for the proposed model.

### E-B — Does calibration transfer?

Fit coefficients on preregistered calibration scenes, freeze them, then evaluate ECE, Gaussian NLL,
coverage, sharpness, and sigma/error correlation on disjoint scenes. Reporting only training-fit
calibration is not evidence of a useful uncertainty model.

### E-C — Is alignment uncertainty predictive?

On paired Sony+iPad scenes, perturb the estimated cross-sensor transform by controlled translation
and rotation. The predicted uncertainty should rise in a way that tracks measured geometry error.
This experiment distinguishes Maveb from pipelines that treat alignment as a binary solved/failed
stage.

### E-D — Does uncertainty help reconstruction, or merely confidence reporting?

Compare identical fusion/training pipelines with uniform, naive confidence, and calibrated
inverse-variance weights. Improvement must be paired per scene and evaluated under view sparsity,
depth dropout, and alignment corruption.

### E-E — Does geometry improve at the expense of appearance?

Report geometry and novel-view metrics jointly. A method that improves Chamfer while materially
worsening LPIPS is a Pareto tradeoff, not an unconditional win.

## 6. Claims Maveb is not allowed to make

Without additional evidence, do not write:

- “first uncertainty-aware Gaussian Splatting method”;
- “first depth-guided Gaussian reconstruction”;
- “first sparse-view Gaussian surface reconstruction”;
- “sensor confidence is a probability”;
- “ARKit high confidence means a fixed metric sigma”;
- “cross-sensor alignment residual equals pointwise depth uncertainty”;
- “photorealistic rendering implies accurate geometry”;
- “synthetic fixture success validates real reconstruction.”

## 7. Current novelty risk

The highest novelty risk is overlap with uncertainty-aware sparse Gaussian methods. The defense is
not terminology. It is experimental design:

- uncertainty originates in *measured heterogeneous sensing and registration signals*;
- it is expressed in metric units;
- it is calibrated before intervention;
- calibration transfer is tested on held-out scenes;
- causal confidence controls are mandatory;
- deliberate sensor/alignment corruption maps the method's failure boundary;
- geometry, rendering, and systems costs are reported together.

If those experiments do not produce a distinct finding, Maveb should narrow or change the claim
rather than inflate the framing.

## 8. Literature-update rule

Before U3 and again before U4, rerun a literature search covering the preceding six months. Any new
method using sensor uncertainty, depth uncertainty, cross-sensor confidence, or sparse Gaussian
surface reconstruction must be added here and assessed for baseline/novelty impact before a paper
claim is frozen.
