# Maveb Metric-Uncertainty Research Results

- Track: calibrated metric geometric uncertainty for sparse reconstruction
- Status: outcome-complete through U6b; U6c is a frozen read-only post-hoc audit
- Primary public evidence: CA-1M/FARO ground truth + ARKitScenes raw confidence
- Final efficacy conclusion: **negative for the tested downstream transfer rules**

## Executive conclusion

The research track separates two questions that must not be conflated:

1. **Does consumer-sensor confidence contain real predictive information about metric depth error?** Yes.
2. **Do the tested hand-designed mappings from that calibrated uncertainty into reconstruction or Gaussian representation reliably improve held-out geometry?** No.

The strongest valid final statement is:

> Sensor confidence genuinely predicts metric error, but the investigated hand-designed mappings from calibrated uncertainty into sparse reconstruction and Gaussian representation do not demonstrate a robust downstream improvement.

The negative downstream conclusion does not invalidate the predictive result. U1b/U2 establish that the uncertainty signal is real; U3 through U6b show that exploiting that signal is representation- and mechanism-dependent, and that several intuitive monotonic transfer rules fail.

No U7 efficacy study is part of Maveb v0.1. The five U6b rooms are exposed and may only support explicitly post-hoc descriptive analysis. Any future efficacy study requires a new prospectively frozen untouched set.

## Result map

| Stage | Design | Outcome | What it establishes |
|---|---|---|---|
| U1a | Calibration | Rejected | A single Gaussian residual likelihood is structurally inadequate for the heavy-tailed metric residuals. |
| U1b | Calibration | Passed | A fixed Student-t(3) model yields a non-saturated confidence-aware predictive uncertainty model. |
| U2 | Held-out predictive test | Passed | Confidence has real held-out predictive information about metric error. |
| U3 | Held-out TSDF intervention | Negative | Direct inverse-variance TSDF weighting does not improve geometry robustly. |
| U3b | Prospective confirmatory TSDF transfer | Negative/null | Relative-confidence precision transfer does not confirm a geometry gain. |
| U3c | Post-hoc mechanism audit | Descriptive | Scalar TSDF weighting often has little mechanical leverage on the tested scenes. |
| U4a | Exploratory support intervention | Negative | Hard uncertainty-anchored support gating removes too much useful support. |
| U5a | Exploratory Gaussian covariance intervention | Negative | Enlarging uncertain Gaussian footprint strongly harms held-out depth quality. |
| U5c | Post-hoc mechanism audit | Descriptive | The covariance failure is dominated by foreground/occlusion leakage. |
| U6a | Exploratory opacity/visibility intervention | Promising signal | Confidence-modulated opacity is directionally positive on exposed rooms. |
| U6b | Prospective confirmatory opacity/visibility | Negative/null | The U6a rule does not robustly generalize to an untouched five-room set. |
| U6c | Post-hoc read-only heterogeneity audit | Descriptive | The U6b effect is highly scene-dependent and concentrated in two rooms. |

---

## U1a — single-Gaussian calibration rejected

Evidence lineage is retained in the protocol and the U1b freeze rather than overwritten.

The original Gaussian residual model was fit on 294,706 deterministic calibration samples. It pushed both geometric noise terms to their upper search bounds and forced many observations against the fixed maximum sigma. Calibration diagnostics showed a distribution with millimetre-scale median error but a severe heavy tail extending far beyond the ordinary residual scale.

This was treated as a model-class failure, not as evidence that confidence was useless.

Rejected predecessor model SHA-256:

`e34bf28d242f5eb7097751263afc79bde25335d08e805cf27b12ef20901a3509`

Primary references:

- `docs/research/METRIC_UNCERTAINTY_PROTOCOL.md`
- `benchmarks/evidence/metric-uncertainty-u1b-freeze-v1.json`

## U1b — fixed Student-t(3) calibration passed

U1b changed only the residual likelihood to fixed Student-t with 3 degrees of freedom; the scene split, samples, uncertainty form, optimization schedule and parameter bounds stayed frozen.

Frozen model SHA-256:

`744cdfce9763f5d2ecd9c9a4e53385f66d8bba7cbc047e11729189053a85e17a`

Fitted parameters:

- depth noise floor: `0.010634156727771725 m`
- quadratic depth term: `0.004398048551220112 m/m^2`
- sensor confidence penalty: `5.990146384791633`
- all fitted-parameter upper-bound flags: `false`

Scene-balanced Student-t NLL improved from:

`-1.3754205957259233 -> -2.3922085805321025`

This model was frozen before held-out sidecar acquisition and sampling.

Evidence:

- `benchmarks/evidence/metric-uncertainty-u1b-freeze-v1.json`

## U2 — held-out predictive uncertainty passed

Five frozen held-out scenes contributed 891,764 observations. The paper-level evidence unit was scene, with 2,000 paired scene-bootstrap replicates and seed 42.

For intact confidence versus within-scene shuffled confidence:

- Student-t NLL: intact better in `5/5` scenes; mean difference `-0.1436841474`; 95% interval `[-0.1839992322, -0.1033690627]`
- expected calibration error: intact better in `5/5`; mean difference `-0.0864501190 m`; 95% interval `[-0.1568174322, -0.0406027291]`
- sigma versus absolute-error correlation: intact better in `5/5`; mean difference `+0.2772274956`; 95% interval `[+0.2599765336, +0.2944784577]`

A post-hoc orientation-witness sensitivity retained 880,689 samples and made the intact-versus-shuffled signal slightly stronger rather than weaker.

**Conclusion:** calibrated sensor confidence carries real held-out predictive information about metric error.

Evidence:

- `benchmarks/evidence/metric-uncertainty-u2-heldout-v1.json`

---

## U3 — direct inverse-variance TSDF weighting negative

U3 tested whether the frozen predictive uncertainty could improve dense CPU TSDF geometry directly.

Candidate calibrated inverse variance versus naive confidence, relative Chamfer improvement:

- scene values: `[-0.031121, +0.030517, -0.112953, +0.050954, -0.015126]`
- median: `-0.0151259948` (`-1.513%`)
- 95% paired scene interval: `[-0.1129526735, +0.0509538149]`

The shuffled-confidence control also failed to show robust degradation. Calibrated-depth-only and calibrated-inverse-variance results were nearly identical.

The preregistered primary gate failed and the result was frozen as negative.

Evidence:

- `benchmarks/evidence/metric-uncertainty-u3-primary-v1.json`
- `benchmarks/evidence/metric-uncertainty-u3-weight-saturation-v1.json`

## U3b — prospective relative-confidence TSDF confirmation negative/null

A new five-room validation set prospectively tested a relative-confidence precision transfer.

Candidate versus naive relative Chamfer improvement:

- median: `-0.00033`
- 95% interval: `[-0.18118, +0.20908]`
- candidate better: `2/5` scenes

Shuffled versus candidate degradation:

- median: `+0.00061`
- 95% interval: `[-0.00186, +0.10481]`
- shuffled worse: `4/5` scenes

Only the shuffled scene-count clause passed; the all-clauses confirmatory gate failed.

**Conclusion:** the relative-confidence precision transfer does not establish a robust TSDF geometry improvement.

Evidence:

- `benchmarks/evidence/metric-uncertainty-u3b-confirmatory-v1.json`

## U3c — scalar fusion has limited mechanical opportunity

U3c is post-hoc mechanism analysis on the already-exposed U3b scenes.

Key observations:

- median naive-versus-relative fusion leverage was exactly zero in all five rooms;
- conflict plus mixed-confidence voxels represented only about `0.498%` to `5.205%` of surface-active voxels;
- only about `2.078%` to `10.968%` of surface-active voxels moved by at least a quarter voxel under the transfer.

This explains how a globally useful predictive uncertainty model can have little effect when used only to re-average near-consensus scalar TSDF observations.

**Mechanistic constraint:** do not keep retuning scalar TSDF weights; if uncertainty is useful downstream, it must act where the representation has real geometric leverage.

Evidence:

- `benchmarks/evidence/metric-uncertainty-u3c-conflict-leverage-v1.json`

---

## U4a — hard uncertainty-anchored support gating negative

U4a moved uncertainty from scalar weighting into support selection on already-exposed rooms.

Candidate versus naive relative Chamfer improvement:

- median: `-0.4062014503` (`-40.620%`)
- candidate better: `0/5` scenes

Candidate versus depth-only:

- median: `-0.0216807037` (`-2.168%`)
- candidate better: `0/5` scenes

The intervention increased precision in places but deleted too much valid support, reducing completeness and worsening Chamfer across every room.

**Conclusion:** hard uncertainty-based observation deletion is not a promising reconstruction mechanism for this setting.

Evidence:

- `benchmarks/evidence/metric-uncertainty-u4a-geometry-v1.json`

---

## U5a — Gaussian covariance enlargement negative

U5a kept Gaussian centers fixed and mapped calibrated uncertainty into Gaussian covariance/footprint.

Candidate minus depth-only primary within-5cm fraction:

- scene values: `[-0.1205924, -0.1319490, -0.1642047, -0.0899146, -0.0488813]`
- median: `-0.1205924347` (`-12.059 percentage points`)
- candidate better: `0/5` scenes

The calibrated-covariance candidate often increased coverage but substantially worsened metric depth error. Intact calibrated association also did not consistently beat shuffled association.

**Conclusion:** the exact frozen rule of enlarging Gaussian covariance monotonically with predicted uncertainty is strongly negative.

Evidence:

- `benchmarks/evidence/metric-uncertainty-u5a-result-v1.json`

## U5c — covariance failure is foreground/occlusion leakage

U5c is a read-only post-hoc audit of the already-rendered U5a outputs.

Across scenes:

- median candidate-only coverage fraction: `0.1414008639`
- median candidate-only foreground-wrong share: `0.8405555370`
- median candidate-versus-depth-only shared absolute-error shift: `+0.2910531759 m`
- median depth-only-correct/candidate-wrong fraction: `0.1205924347`
- reverse candidate-correct/depth-only-wrong fraction: only `0.0010117649`

Shuffled covariance was at least as foreground-leaky as intact calibrated covariance at the scene-median level.

**Mechanistic conclusion:** footprint enlargement itself promotes uncertain splats to incorrect foreground occluders. Uncertainty should not be mapped monotonically into larger Gaussian spatial support under this renderer/depth rule.

Evidence:

- `benchmarks/evidence/metric-uncertainty-u5c-occlusion-audit-v1.json`

---

## U6a — opacity/visibility showed an exploratory positive signal

U6a kept centers and covariance fixed and changed only Gaussian opacity/visibility using frozen calibrated relative precision.

Candidate minus fixed-opacity baseline:

- median: `+0.0039694014` (`+0.397 percentage points`)
- candidate better: `4/5` exposed rooms

Candidate minus shuffled-opacity control:

- median: `+0.0042239107` (`+0.422 percentage points`)
- candidate better: `4/5`

The strongest exposed room improved correctness while coverage decreased modestly and MAE/p95 improved substantially, making visibility modulation mechanistically more plausible than covariance enlargement.

Because U6a used already-exposed rooms and targets, it was never efficacy evidence. It justified exactly one prospectively frozen untouched confirmation with no retuning.

Evidence:

- `benchmarks/evidence/metric-uncertainty-u6a-result-v1.json`

## U6b — prospective opacity/visibility confirmation negative/null

U6b prospectively froze five untouched rooms, three methods and eight targets per room before the confirmatory reveal.

Execution:

- `5` scenes
- `3` methods
- `8` targets per scene
- `120` sealed confirmatory renders
- renderer SHA-256: `6b1f511633c259890b0f531ac414773a6a2bcbfcf5ee932585db036cfd4a997d`
- result SHA-256: `c361fda74d005c3d76c2d33b83626e5ef4039ee9fbce177d0b42e42fc9a0a823`

Candidate versus fixed-opacity baseline:

- scene effects: `[+0.0155930434, 0.0, -0.0004408314, +0.0001082957, +0.1258898836]`
- median: `+0.0001082957`
- paired 95% lower bound: `-0.0004408314`
- scene wins: `3/5`

Candidate versus shuffled-confidence opacity:

- scene effects: `[+0.0091825978, 0.0, -0.0005013777, -0.0003917756, +0.1236564595]`
- median: `0.0`
- paired 95% lower bound: `-0.0005013777`
- scene wins: `2/5`

Coverage safeguards passed:

- median candidate/baseline coverage ratio: `0.9966691166`
- minimum scene coverage ratio: `0.9234617646`

The overlap-MAE guard failed (`3/5` scenes no worse than baseline; required `4/5`). Seven of the nine frozen gate checks failed; only the two coverage checks passed.

**Confirmatory decision:** `completed-confirmatory-gate-not-passed`.

The null is not explained by catastrophic visibility collapse. Instead, the candidate failed to show a sufficiently consistent effect and did not robustly beat the shuffled-confidence causal control.

The five confirmatory rooms are now exposed. No opacity exponent, base opacity, floor, clipping, alpha cutoff, covariance, source/target selection, metric, bootstrap or gate threshold may be retuned on them to rescue the claim.

Evidence:

- `benchmarks/evidence/metric-uncertainty-u6b-result-v1.json`
- `benchmarks/evidence/metric-uncertainty-u6b-result-freeze-v1.json`

## U6c — frozen read-only heterogeneity audit

U6c reads only the sealed U6b result JSON. It does not read render files, rerender, recompute FARO metrics, recompute the gate/bootstrap, fit a transfer rule, or drop/reweight rooms.

Evidence SHA-256:

`91f63bda81766f37fe14b68d54dafb60a8142e0b7152a03422cb1110bfb5d9a6`

Commit:

`a2725ff296d34ec4c0c33103b5199334aa70a40d`

Descriptive ranking versus baseline:

1. `ca1m-47331971`: `+0.1258898836`
2. `ca1m-42898811`: `+0.0155930434`
3. `ca1m-47332915`: `+0.0001082957`
4. `ca1m-45261121`: `0.0`
5. `ca1m-47895341`: `-0.0004408314`

Descriptive ranking versus shuffled:

1. `ca1m-47331971`: `+0.1236564595`
2. `ca1m-42898811`: `+0.0091825978`
3. `ca1m-45261121`: `0.0`
4. `ca1m-47332915`: `-0.0003917756`
5. `ca1m-47895341`: `-0.0005013777`

Target-level evidence reinforces the heterogeneity:

- `ca1m-42898811`: candidate beat baseline on `7/8` targets and shuffled on `7/8`;
- `ca1m-47331971`: candidate beat baseline on `6/8` and shuffled on `6/8`;
- `ca1m-45261121`: all primary target deltas were exactly zero;
- `ca1m-47895341`: candidate beat each control on only `1/8` targets;
- `ca1m-47332915`: candidate beat baseline on `1/8` and shuffled on `0/8`.

The two responsive rooms also show different effect scales, with `ca1m-47331971` dominating the cross-scene range. This supports a scene-dependent interaction hypothesis, not a general efficacy claim.

**Interpretation boundary:** U6c may describe heterogeneity in the already-sealed negative/null U6b result. It cannot rescue U6b, justify retuning on the five exposed rooms, or support a new confirmatory efficacy claim.

Evidence:

- `benchmarks/evidence/metric-uncertainty-u6c-heterogeneity-audit-v1.json`

---

## What the complete track means

### Supported

- Consumer-sensor confidence has real predictive value for metric depth error on disjoint held-out data.
- A robust heavy-tail likelihood is materially better suited than the rejected single-Gaussian calibration model.
- Downstream usefulness depends on the mechanical leverage and failure modes of the representation.
- Post-hoc mechanism audits can explain negative interventions without changing their decisions.

### Not supported

- A general claim that calibrated uncertainty improves sparse TSDF geometry via inverse-variance weighting.
- A general claim that uncertainty-based hard support selection improves geometry.
- A general claim that uncertain Gaussians should be spatially enlarged.
- A general claim that the frozen confidence-to-opacity rule improves Gaussian visibility on unseen scenes.

## Research closure policy

For Maveb v0.1 this research track is closed after documentation and CI/review.

There is no U7 intervention in this release. The correct next project work is engineering completion:

1. one releasable real captured-world end-to-end proof;
2. named renderer/performance benchmarks;
3. AetherStudio workflow polish;
4. clean-clone reproducibility and release packaging.

If future research revisits uncertainty-to-representation transfer, it must begin with a new mechanism derived without efficacy tuning on the U6b five-room confirmatory set and must prospectively freeze a genuinely untouched evaluation set before outcome exposure.
