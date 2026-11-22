# MAVEB CBRC numerical laboratory — when is a local repair justified?

Read [RevisionPlanner.cpp](../engine/revision/src/RevisionPlanner.cpp), [CapturedWorldRevisionGraph.cpp](../engine/cbrc/src/CapturedWorldRevisionGraph.cpp) and [GaussianLocalityCertificate.cpp](../engine/world_gaussian/src/GaussianLocalityCertificate.cpp). The earlier [CBRC edit-to-certificate walkthrough](CBRC_FROM_EDIT_TO_CERTIFICATE.md) is the broader system story. This lesson works through the actual formulas and the boundary between analytical guarantees, execution, and research evidence.

## 1. What the graph says

A captured world may contain observations, sparse TSDF, owner mesh patches, texture/material state, changed Gaussians, GPU publication and temporal/image QoI state. These are connected by typed dependency edges. The generic planner owns **nodes, workCost, changeBound, hard/empirical predecessors, analytic influence gains and QoIs**.

HARD means the target cannot be considered correctly repaired without exact upstream prerequisite closure. EMPIRICAL evidence may inform performance, but without a certified analytic upper bound it is also treated as an exact prerequisite. ANALYTIC edges permit conservative residual propagation into nodes outside the repaired cone.

The graph is a *planning contract*, not a scheduler that automatically issues Metal dispatches. The relevant representation-specific engines still implement updates, and an independent full recomputation oracle is needed for empirical comparison.

## 2. An exact closure worked by hand

Suppose the nodes are O (observation), T (TSDF), M (mesh), and G (Gaussian). Hard edges O→T and T→M mean M has exact predecessors T and O. There is an analytic G→image relation that can bound the effect of leaving G unchanged.

If an edit seed requires M, RevisionGraph::closeExactPredecessors({M}) yields {O,T,M}, not only {M}. A cone containing M without T or O is rejected even when the nominal workCost looks attractive. Sorted deterministic closure avoids duplicate node IDs and is used by the certificate.

**Exercise:** add a second hard predecessor P→M and compute closure for seeds {M,T}. Explain why duplicate seeds do not count work twice.

## 3. Propagating a conservative exterior error

For outside node j, imagine a source bound b_j and an analytic edge i→j of gain g_ij. A safe additive bound under the declared model is

\[
r_j \le b_j + \sum_{\text{incoming analytic }i\to j} g_{ij} r_i.
\]

Nodes inside the actual repair cone are assigned zero residual for this calculation; exterior nodes are processed in topological order. If the analytic exterior contains a cycle, this implementation fails closed instead of solving a cyclic fixed-point problem with assumptions it has not certified.

**Worked example:** let the image-response node receive residual 0.02 from source uncertainty plus gain 0.5 from an exterior Gaussian-response node whose residual bound is 0.1. Then image residual bound is 0.02+0.5×0.1=0.07. If the declared image QoI tolerance is 0.05, that LOCAL cone fails. If the Gaussian source is recomputed inside the cone and the direct 0.02 source remains, the bound falls to 0.02 and can pass—provided exact closure and all other QoIs also pass.

Every QoI can contain multiple weighted terms. A passing single image metric does not allow another required geometry or temporal tolerance to be ignored.

## 4. Why greedy LOCAL is not globally optimal

greedyCertifiedRevisionCone begins with mandatory hard closure, checks certification, and tries adding candidate nodes along with their required exact prerequisites. Each candidate is re-certified. The heuristic prefers candidates that pass, then compares reduction of violation score against additional calibrated work.

It returns a passing cheaper LOCAL cone when available. Otherwise it certifies the complete node set and marks FULL fallback when no cheaper certified subset is selected. This is a robust decision policy under the declared bounds, **not a mathematical proof of the minimum-work subset**.

A node with small workCost may trigger expensive hard prerequisites, so candidate extraWork is calculated on the complete closure, not the one explicitly selected node.

## 5. From real locality counts to abstract work

CapturedWorldRevisionGraph.cpp consumes LocalityLedger counters and mesher statistics, checking that mesh-cell/patch counts and Gaussian full baselines agree. It maps each counter to cost using a **versioned calibrated cost model**, constructs exact and analytic links, declares RGB L-infinity QoI, and asks the generic planner for a cone.

Calibrated work is neither CPU/GPU wall time nor a paired speedup measurement. To support a performance claim, run matched local and full repair on the same scene edit with equal correctness thresholds, warm-up, synchronized GPU timings and repeated trials. The frozen published work-reduction ledger must retain its exact source revision.

## 6. How Gaussian tails enter a bound

For a changed anisotropic Gaussian with unit rotation quaternion R and log-scale components \(\ell_i\), its world covariance is

\[
\Sigma = R\,\operatorname{diag}(e^{2\ell_1},e^{2\ell_2},e^{2\ell_3})R^T.
\]

Its opacity is alpha = sigmoid(opacityLogit). The implementation checks all parameters for finite values, near-unit quaternion norm, and safe positive variances before evaluating any bound.

For an edit AABB face at distance d along axis a from Gaussian mean, its conservative one-axis density-tail proxy is

\[
T_a = \alpha \exp\!\left(-\frac{d^2}{2\Sigma_{aa}}\right)
\]

when the mean is inside the corresponding face. If the mean is already at or outside that face, the function uses full alpha instead of pretending the exterior influence decays.

There are six face contributions, minimum and maximum for each axis. accumulate sums them for both **beforeChanged** and **afterChanged** splats. The returned outsideDensityBound is the largest accumulated face value.

**Numerical example:** opacity alpha=0.5, diagonal variance=1 and face distance=2. Tail is \(0.5e^{-2}\approx0.06767\). With distance 0, the full alpha 0.5 applies. This is a density upper contribution at a face, **not automatically an RGB L-infinity pixel bound**: projection, transmittance, blending, color and temporal history require their own certified connection.

## 7. Spatial, image and temporal guarantees are different

GaussianLocalityCertificate concerns a 3D density proxy. GaussianImageRevisionCertificate and GaussianRenderCertificate inspect image-domain effects under additional model/camera assumptions. TemporalRevisionCertificate considers history propagation and temporal weight. A camera change or invalid history can break a previous local-frame argument.

The planner treats temporal validation stability explicitly. When it fails, history dependency may be upgraded to a hard relation rather than trusting an analytic blend factor. That is fail-closed behavior rather than assuming all changes remain local.

**Exercise:** compare an opacity-only edit to a position edit that crosses an image boundary. Explain why proving a small 3D Gaussian tail does not alone prove equal composited pixels and why a full-render oracle remains valuable.

## 8. Verification and falsification

Read [RevisionPlannerTests.cpp](../tests/RevisionPlannerTests.cpp), [GaussianLocalityCertificateTests.cpp](../tests/GaussianLocalityCertificateTests.cpp), [GaussianImageRevisionCertificateTests.cpp](../tests/GaussianImageRevisionCertificateTests.cpp) and [TemporalRevisionCertificateTests.cpp](../tests/TemporalRevisionCertificateTests.cpp). Add cases for missing hard closure, analytic cycle, nonfinite gain, overflowed residual, QoI violation, zero or near-zero Gaussian variance and a changed primitive outside the edit face.

For a paper table, preserve error metric, QoI epsilon, exact test revision, scene seed, camera, representation version, all source counters and GPU/CPU measurement method. **No observed failure in a finite suite is not a universal proof**, and a work proxy is not speedup.

*Documentation-only derivation; no new compiler run or experimental measurement was performed in this pass.*
