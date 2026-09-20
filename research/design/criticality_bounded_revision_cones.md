# Criticality-Bounded Revision Cones (CBRC)

Status: mathematical research candidate; not yet a novelty or correctness claim.
Parent problem: MAVEB-CLOSURE.

## 1. Motivation

A dependency closure answers a Boolean question: can a changed state reach another state?

That is insufficient for a captured world. Many physical/rendering dependencies have rapidly decaying
influence: Gaussian tails, filter footprints, temporal weights, bounded spatial fusion support, and
screen-space support. Other dependencies are hard/exact: entity identity, ownership, topology,
archive/provenance and explicit region membership.

CBRC separates those two cases.

The proposal is to replace a fixed "dirty halo" by a **certified revision cone** whose frontier stops
when all unrepaired influence outside the cone is provably below the declared output tolerance.

The cross-domain analogy is deliberately physical:

- Lieb-Robinson locality: local perturbations have an approximate finite-speed influence cone.
- Nuclear/branching criticality: one affected unit can create more or less than one unit of downstream
  normalized influence.
- Statistical mechanics: exponentially attenuated paths compete against exponentially many paths;
  their balance determines whether influence localizes or delocalizes.
- Adaptive PDE methods: repair should be driven by an a-posteriori bound on the quantity of interest,
  not by geometric distance alone.

None of those analogies is itself a novelty claim. The candidate contribution is their rigorous
specialization to heterogeneous captured-world revision.

## 2. Typed revision state

Let V be typed state blocks:

    observations, TSDF blocks, mesh patches, Gaussian clusters,
    texture/material pages, GPU publication spans, temporal-history tiles.

Each v in V has a state space X_v and a declared tolerance tau_v > 0 for the continuous quantity being
certified. Define normalized error

    z_v = ||x_v^inc - x_v^full||_v / tau_v.

A discrete state whose mismatch is never acceptable is handled separately as a hard dependency and
does not receive a finite approximation tolerance.

A physical revision Delta produces a source vector b >= 0 in normalized units.

## 3. Hard closure first

Let E_h be hard dependencies: identity, ownership, topology, exact dirty-region membership,
provenance/archive obligations, explicit delete/insert semantics, and any quantity whose contract is
exact equality.

Compute the exact hard closure H(Delta). All members of H must be repaired.

CBRC is applied only to the remaining continuous/approximate influence outside H. This prevents a
small numerical tolerance from silently weakening discrete correctness.

## 4. Local gain operator

For each soft dependency u -> v define a safe local gain

    K_vu >= sup || d F_v / d x_u || * tau_u / tau_v.

K is dimensionless and non-negative. The tolerance scaling is essential: one millimeter, one texel,
one Gaussian opacity perturbation and one history-pixel error cannot be added before normalization.

For finite perturbations, K_vu may be a certified secant/Lipschitz upper bound rather than a Jacobian.

The bound propagation is

    z^(r+1) <= K z^(r)

with z^(0)=b. Hence influence arriving after exactly r soft propagation steps is bounded by

    z^(r) <= K^r b.

Graph causality gives a finite-speed property automatically: if d(S,v) > r then (K^r b)_v = 0.

## 5. Revision multiplication factor

Using a fixed physically meaningful weighted 1-norm,

    ||z||_w = sum_v w_v |z_v|,

define

    kappa_Delta = ||K||_w
                = sup_{z != 0} ||K z||_w / ||z||_w.

Interpretation:

- kappa < 1: every propagation shell contracts in the certified norm.
- kappa ~= 1: critical revision; correlation length becomes large.
- kappa > 1: no contraction certificate exists; local repair may fan out faster than influence decays.

This is more appropriate than using only spectral radius. A finite DAG has spectral radius zero even
when one changed node fans out to most of the world before termination. kappa measures that finite
fan-out under fixed output tolerances.

For cyclic/repeated local structures, rho(K) may also be reported as an asymptotic diagnostic, but it
is not the primary safety criterion.

## 6. Tail theorem

If kappa < 1, submultiplicativity gives

    ||K^r b||_w <= kappa^r ||b||_w.

Therefore the total not-yet-accounted influence after stopping at propagation radius R is bounded by

    Tail(R)
      = sum_{r=R+1}^infinity ||K^r b||_w
      <= ||b||_w * kappa^(R+1) / (1-kappa).

For a residual budget epsilon, a sufficient stopping radius is the smallest R satisfying

    ||b||_w * kappa^(R+1) / (1-kappa) <= epsilon.

Equivalently,

    R >= log(epsilon (1-kappa) / ||b||_w) / log(kappa) - 1,

with the usual care that log(kappa) < 0.

This is the core mathematical replacement for an arbitrary dirty halo.

## 7. Revision correlation length

For 0 < kappa < 1 define

    xi_Delta = -1 / log(kappa_Delta).

Then influence scales no slower than exp(-r / xi_Delta) in propagation-shell distance.

As kappa -> 1 from below,

    xi_Delta -> infinity.

This predicts a critical regime in which a physically small edit can require a macroscopically large
repair cone.

## 8. Path action and revision free energy

For a path p=(e_1,...,e_m), let the edge gains be g_e and define path action

    A(p) = - sum_e log g_e.

Its multiplicative influence is

    exp(-A(p)) = product_e g_e.

For all paths of shell length r, define the path partition sum

    Z_r = sum_{p: |p|=r} exp(-A(p)).

Then define revision free energy

    F_r = -log Z_r.

This exposes the mechanism behind criticality:

- attenuation increases A(p) with distance;
- branching increases the number of available paths (path entropy);
- if attenuation wins, F_r grows and influence localizes;
- if path entropy wins, F_r stops growing and the revision delocalizes.

For a homogeneous B-way branching system with edge gain g,

    Z_r = (B g)^r.

The critical point is exactly

    B g = 1.

That is the chain-reaction analogy in mathematical form: B is effective branching, g is retained
influence, and B*g is the revision multiplication factor.

## 9. Repair nodes as absorbing boundaries

Repairing a node sets its error relative to the declared full reference back to zero (or to a known
post-repair residual). A repair set R therefore acts as an absorbing boundary for stale influence.

Let M_R be a diagonal mask that is zero on repaired nodes and one elsewhere. A conservative residual
bound is generated by repeated application of

    K_R = M_R K M_R.

When ||K_R||_w < 1,

    z_res <= sum_{r=0}^infinity K_R^r M_R b
          = (I-K_R)^(-1) M_R b.

This yields a minimum-work formulation:

    minimize_R   W(R) = sum_{v in R} c_v

    subject to   Q_j z_res <= epsilon_j   for every declared quantity of interest j,
                 H(Delta) subseteq R.

Exact/discrete quantities are enforced by H. Continuous outputs use finite epsilon_j.

The exact combinatorial optimum need not be solved in the first implementation. A certified frontier
algorithm can expand the cone by maximum bound-reduction per unit repair work until all residual
budgets pass.

## 10. Why this is stronger than ordinary dependency propagation

A Boolean dependency graph asks whether a path exists.

CBRC asks four additional questions:

1. How much normalized influence can each dependency transmit?
2. Does influence contract or multiply as the frontier expands?
3. What is the certified residual influence outside the chosen repair cone?
4. At what criticality should the system stop being incremental and rebuild globally?

The result is not "update reachable nodes." It is "repair the minimum certified cone and prove the
unrepaired exterior cannot alter the declared output beyond tolerance."

## 11. Candidate captured-world gains

Initial safe gain families to derive/measure:

### Gaussian spatial tails

For Gaussian i with covariance Sigma_i, an outside-support density influence can be bounded by the
existing Gaussian-tail locality certificate. This becomes a spatial soft edge gain rather than a
binary infinite-radius dependency.

### Temporal history

For a history blend coefficient alpha in a stable valid region, repeated temporal influence forms a
geometric series. The gain contributes approximately alpha, with disocclusion/reprojection failures
promoted to hard invalidation.

### Texture filtering

Footprint/filter weights give bounded local gains. Page ownership/address changes remain hard.

### TSDF / mesh

Truncation support and dirty-block ownership are primarily hard/local. Any interpolation/normal
pollution beyond exact ownership may receive an explicit soft bound only after derivation.

### GPU publication

Record identity/range publication is hard and exact; no approximation is allowed merely to save
bytes.

## 12. Fallback law

CBRC should not always prefer local repair.

Proposed policy:

    if hard closure is already macroscopic:
        full rebuild
    elif kappa_Delta <= 1-gamma and Tail(R*) <= epsilon:
        execute certified local cone R*
    elif kappa_Delta is near one:
        expand conservatively and compare predicted local/full work
    else:
        full rebuild

Thus the method explains the incremental/full crossover rather than hiding it.

## 13. Main falsifiable hypotheses

C1. Sparse real-world revisions frequently enter a subcritical regime kappa_Delta < 1 under fixed,
predeclared output tolerances.

C2. Tail-certified cones are substantially smaller than Boolean transitive closures while satisfying
the same declared full-reference tolerance.

C3. xi_Delta predicts measured repair radius and the local/full crossover better than changed-world
fraction alone.

C4. Critical/supercritical revisions can be detected before paying most of the local-repair cost,
making fallback cheaper than blindly expanding a dependency closure.

C5. The free-energy slope F_(r+1)-F_r distinguishes localizable from delocalizing revision classes.

## 14. Kill tests

Kill CBRC if:

- useful safe edge gains cannot be bounded without effectively running the full reference;
- realistic gains make kappa >= 1 for nearly every nontrivial revision;
- certified cones are not meaningfully smaller than Boolean closure;
- correlation length fails to predict measured frontier growth/crossover;
- required tolerances are so loose that the certificate is scientifically uninteresting;
- closest prior art is found that already applies correlation-decay/light-cone criticality to
  heterogeneous captured-world reconstruction and rendering updates.

## 15. Current novelty status

A current search found extensive prior art in self-adjusting computation, correlation-decay local
algorithms, Lieb-Robinson locality, adaptive PDE error estimation, and dependency-driven rendering.
Those are foundations and must be cited.

The search did not identify the combined construction above for persistent captured-world revision.
That absence is not proof of worldwide novelty. The candidate must continue to be attacked before
publication.

MATHEMATICAL_DESIGN_MATURITY = approximately 0.65
IMPLEMENTATION_EVIDENCE = false
NOVELTY_PROVEN = false
