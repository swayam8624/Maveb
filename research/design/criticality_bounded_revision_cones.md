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
certified. First distinguish **true revision change** from **algorithmic stale error**.

Let

    delta x_v = x_v^(full-after) - x_v^(before)

and define normalized true-change magnitude

    z_v = ||delta x_v||_v / tau_v.

If v is left unrepaired at its before-revision value, its local stale error is bounded by z_v. If v
is repaired, its own stale error becomes zero, but its corrected value may still induce a nonzero
true revision change in downstream dependents. Repair therefore does **not** absorb physical
influence.

A discrete state whose mismatch is never acceptable is handled separately as a hard dependency and
does not receive a finite approximation tolerance.

A physical revision Delta produces a source true-change vector b >= 0 in normalized units.

## 3. Hard closure first

Let E_h be hard dependencies: identity, ownership, topology, exact dirty-region membership,
provenance/archive obligations, explicit delete/insert semantics, and any quantity whose contract is
exact equality.

Compute the exact hard closure H(Delta). All members of H must be repaired.

CBRC is applied only to the remaining continuous/approximate influence outside H. This prevents a
small numerical tolerance from silently weakening discrete correctness.

### Soft-to-hard boundary rule

The hard closure cannot be computed from physical source nodes alone. A revision may travel first
through a bounded soft edge and then reach an exact dependency. Suppose a state u has a non-zero
true-change bound and an exact/empirical-only edge u -> v, and v also has a non-zero true-change
bound. Leaving v stale would violate the exact-state contract even if the influence that reached u
was small.

Therefore the required repair seed is closed under:

1. ordinary forward HARD/EMPIRICAL propagation from physical sources;
2. every HARD/EMPIRICAL edge whose source and target both have non-zero true-change bounds; and
3. active predecessor closure for all states thereby forced into repair.

This prevents a soft -> hard transition from disappearing merely because hard edges are intentionally
absent from the approximate transfer matrix K. A hard target whose certified true-change bound is
exactly zero need not be repaired because its before and full-after states coincide.

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

## 6.1 Revision Green's function and susceptibility

For any unrepaired exterior O for which the response is stable, define

    G_O = (I-K_OO)^(-1).

G_O is the **revision response Green's function**: its entry (v,u) upper-bounds the accumulated
normalized true-change response at v induced by one unit of frontier change at u through every
admissible exterior propagation path.

Define global exterior susceptibility

    chi_O = ||G_O||_w

and, more usefully for a specific revision/frontier direction,

    chi_O(f) = ||G_O f||_w / ||f||_w.

Then the exterior stale-error certificate is

    ||z_O||_w <= chi_O(f_O) ||f_O||_w.

This quantity is superior to spectral radius alone for finite captured-world graphs. A DAG has
rho(K)=0 but may still have enormous transient fan-out. G_O sums that finite path amplification
exactly. In cyclic systems, chi grows rapidly as the response approaches criticality.

Cheap safe bound:

    if kappa_O = ||K_OO||_w < 1,
    then chi_O <= 1/(1-kappa_O).

For acyclic exteriors, K_OO is nilpotent and G_O is a finite polynomial even when kappa_O >= 1.
Therefore kappa is a sufficient contraction test, not the sole definition of criticality.

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

## 9. Repair frontier theorem

A repair cone C is a predecessor-consistent set containing the exact hard closure H(Delta). Let O be
its unrepaired exterior.

Partition K as

    [ K_CC  K_CO ]
    [ K_OC  K_OO ]

under the ordering (C,O). After the repaired cone has computed a safe bound z_C on its own true
revision change, the normalized revision-change flux crossing into the stale exterior is

    f_O = b_O + K_OC z_C.

Usually b_O=0 because physical evidence sources are inside C, but it is kept explicit.

The unrepaired exterior's true change satisfies

    z_O <= f_O + K_OO z_O.

If the exterior multiplication factor

    kappa_O = ||K_OO||_w

is less than one, then the Neumann bound gives

    ||z_O||_w
      <= ||(I-K_OO)^(-1) f_O||_w
      <= ||f_O||_w / (1-kappa_O).

If O is left stale, this bound is also a bound on its residual stale error relative to the declared
full-after state.

This is the key stopping certificate:

> Stop expanding the repair cone only when the true-change flux crossing its frontier, multiplied by
> the worst-case exterior amplification, fits inside every declared output tolerance.

For a quantity-of-interest map Q_j, a sharper condition is

    || Q_j (I-K_OO)^(-1) f_O || <= epsilon_j.

For exact/discrete outputs, the relevant dependencies remain in the hard closure instead of using
this approximate certificate.

## 9.1 Minimum-work cone

The principled optimization is therefore

    minimize_C   W(C) = sum_{v in C} c_v

    subject to   H(Delta) subseteq C,
                 C is dependency/predecessor consistent,
                 Q_j (I-K_OO)^(-1) f_O <= epsilon_j  for every QoI j.

The first implementation need not solve this combinatorial optimization exactly. A certified
frontier expansion can repeatedly add the boundary region with the best predicted reduction in the
exterior residual bound per unit repair work, stopping only when all certificates pass.

A simple radius-R cone yields the earlier geometric tail theorem as a special case.

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

C2. Frontier-flux-certified cones are substantially smaller than Boolean transitive closures while
satisfying the same declared full-reference tolerance.

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

## 14.1 Important collision notes

The vocabulary "influence" and "susceptibility" is **not** novel. Engineering design-change research
has used dependency matrices and dominant eigenvectors to rank component influence/susceptibility
under cyclic change propagation (Sarica & Luo, IEEE Systems Journal 2019). CBRC therefore must not
claim generic susceptibility analysis.

Likewise:

- self-adjusting computation already tracks dependencies and re-executes affected computation;
- correlation-decay algorithms already justify local computation in other graph problems;
- goal-oriented adaptive PDE methods already use local error estimators to minimize work for a QoI;
- incremental rendering already tracks affected render regions/caches;
- differentiable rendering computes scene-to-image sensitivities;
- recent Gaussian-splatting work analytically quantifies some per-Gaussian rendering errors.

The surviving candidate distinction is the **typed captured-world frontier theorem**: physical evidence
revision -> exact hard closure -> tolerance-normalized heterogeneous transfer operator -> boundary
change flux -> exterior Green's-function response bound -> minimum-work certified repair cone ->
principled local/full crossover.

Key neighboring references to keep in the attack set:

- Acar, *Self-Adjusting Computation*, CMU-CS-05-129.
- Wörister et al., *Lazy Incremental Computation for Efficient Scene Graph Rendering*, HPG 2013.
- Sarica & Luo, *An Infinite Regress Model of Design Change Propagation in Complex Systems*,
  IEEE Systems Journal 2019, DOI 10.1109/JSYST.2019.2899988.
- Gamarnik et al., correlation-decay methods for local network algorithms.
- Goal-oriented/local a-posteriori error estimation literature for adaptive PDEs.
- 2026 algorithmic-locality/light-cone work in tensor-network message passing.
- GaussianPOP (2026) and other analytical Gaussian rendering-error work.

## 15. Current novelty status

A current search found extensive prior art in self-adjusting computation, correlation-decay local
algorithms, Lieb-Robinson locality, adaptive PDE error estimation, and dependency-driven rendering.
Those are foundations and must be cited.

The search did not identify the combined construction above for persistent captured-world revision.
That absence is not proof of worldwide novelty. The candidate must continue to be attacked before
publication.

MATHEMATICAL_DESIGN_MATURITY = approximately 0.70
IMPLEMENTATION_EVIDENCE = false
NOVELTY_PROVEN = false
