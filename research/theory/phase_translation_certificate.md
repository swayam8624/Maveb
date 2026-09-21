# Restricted Phase-Translation Certificate

**Status:** mathematical working note, not a paper claim
**Date:** 2026-09-20

## 1. Scope

This note deliberately states a **restricted** result.

It does **not** claim that spectral phase is a universal geometry invariant for 3D Gaussian
Splatting. MAVEB's own `phase-representation-nuisance-v1` rejected raw anisotropic,
opacity-weighted Gaussian-field phase as a geometry-only invariant, and
`local-phase-contamination-v4` showed that a mixed stationary/moving neighborhood can produce a
high-coherence phase signal whose estimated translation is closer to aggregate motion than maximum
point motion.

The model below applies only after:

1. Gaussian appearance/footprint nuisance has been canonicalized away, e.g. equal isotropic kernels
   at Gaussian centers;
2. one local support/neighborhood has been isolated;
3. that support is assumed to undergo one coherent translation;
4. only Fourier modes with non-negligible magnitude are used;
5. the displacement is small enough for selected phase increments to be unwrapped uniquely, or a
   correct unwrapping is otherwise provided.

The point of the theorem is to make the assumption and conditioning explicit.

## 2. Exact translation relation

Let a canonical local density be

[
f(x)=sum_i w_i,kappa(x-mu_i),
]

with a shared isotropic kernel (kappa). For a coherent translation (d),

[
g(x)=f(x-d).
]

By the Fourier shift theorem,

[
G(k)=F(k)e^{-i k^	op d}.
]

Therefore, for every non-degenerate Fourier mode (k) with (F(k)
eq 0),

[
Deltaphi_k = arg(G(k)F(k)^*) = -k^	op d pmod{2pi}.
]

When the selected modes are correctly unwrapped, stack them into

[
y=-A d,
]

where row (A_k=k^	op).

This is the mathematical sanity relation verified numerically by
`phase-shift-sanity-v2`.

## 3. Noisy weighted estimate

Suppose measured unwrapped phase increments satisfy

[
	ilde y=-A d + e.
]

Let (Wsucceq0) be a diagonal mode-weight matrix, for example derived from shared spectral
magnitude after rejecting near-zero modes. Define

[
hat d = argmin_z |W^{1/2}(Az+	ilde y)|_2^2.
]

If (W^{1/2}A) has rank three, then

[
hat d-d = -(W^{1/2}A)^+ W^{1/2}e.
]

Hence

[
oxed{
|hat d-d|_2
le
rac{|W^{1/2}e|_2}
{sigma_{min}(W^{1/2}A)}
}
]

where (sigma_{min}) is the smallest singular value.

If an assumption supplies a per-mode phase-error bound

[
|e_k|le epsilon_infty,
]

then

[
|W^{1/2}e|_2
le
epsilon_inftysqrt{sum_k w_k}
]

and therefore

[
oxed{
|hat d-d|_2
le
rac{epsilon_inftysqrt{sum_k w_k}}
{sigma_{min}(W^{1/2}A)}
}.
]

This is a **computable conditional certificate** once a justified phase-error bound is available.

## 4. Unwrapping condition

A sufficient small-motion condition for principal-phase uniqueness on selected modes is

[
|k^	op d| < pi
quad orall kin K.
]

A conservative condition is

[
|d|_2 < rac{pi}{max_{kin K}|k|_2}.
]

In practice a safety margin should be used.

This creates an explicit tradeoff:

- higher frequencies improve spatial sensitivity/conditioning;
- higher frequencies reduce the unambiguous displacement radius and are more fragile near spectral
  zeros/resampling noise.

That tradeoff is experimentally testable.

## 5. What the residual does **not** certify

The weighted residual

[
r=W^{1/2}(Ahat d+	ilde y)
]

is useful for model diagnostics, but it is not by itself an upper bound on translation error.
Error components lying in the column space of (A) can bias (hat d) while leaving a small
residual.

MAVEB's `local-phase-contamination-v4` demonstrates exactly this failure mode: a mixture of
stationary and translated support can keep spectral coherence extremely high while biasing the
estimated displacement roughly toward aggregate motion.

Therefore:

> **Low phase residual/coherence is not a preservation certificate unless coherent-support
> membership is independently justified.**

## 6. Research implication

The plausible publishable mechanism is no longer "phase preserves geometry."

It is closer to:

1. partition/correspond local geometric support so each certified neighborhood satisfies a restricted
   motion model;
2. canonicalize representation nuisance;
3. use phase only where it adds an analytically useful displacement relation;
4. compute conditioning/unwrapping limits;
5. reject neighborhoods that fail support/model assumptions;
6. combine the certificate with explicit surface/density constraints for non-rigid or mixed support.

A useful paper result would need to show that this conditional certificate reduces off-target
geometric damage or detects unsafe edits better than simpler direct constraints.

## 7. Immediate falsification targets

- Inject bounded phase noise and verify the singular-value error bound numerically.
- Vary frequency subsets to map conditioning versus unambiguous-displacement radius.
- Apply split/merge resampling and estimate an empirical/analytic phase-error envelope.
- Test whether support partitioning or lineage can detect the mixed-motion contamination that phase
  residual alone misses.
- Compare the resulting certificate against direct center, surface-anchor, rigidity and canonical
  density constraints.
