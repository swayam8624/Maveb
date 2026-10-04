# Gaussian Tail Locality Certificate — Research Note

**Date:** 2026-09-20
**Status:** analytic candidate; novelty unverified; not yet a rendering-space theorem.

## Setup

Let a Gaussian density primitive be

[
g_i(x)=alpha_iexp!left[-rac12(x-mu_i)^TSigma_i^{-1}(x-mu_i)ight],
]

with (alpha_ige 0), positive-definite (Sigma_i), and scene density

[
ho(x)=sum_i g_i(x).
]

Suppose an edit modifies only primitive set (M). Unmodified primitives cancel exactly between before/after fields, so

[
|ho_1(x)-ho_0(x)|
le
sum_{iin M}left(g_i^0(x)+g_i^1(x)ight).
]

Let the allowed edit volume be the axis-aligned box

[
Omega=[ell_x,u_x]	imes[ell_y,u_y]	imes[ell_z,u_z].
]

Its complement is the union of six coordinate halfspaces.

## Single-Gaussian halfspace bound

Consider one face, for example (x_jle ell_j), with a Gaussian mean on the interior side. The minimum Mahalanobis squared distance from (mu) to that halfspace boundary is the linearly constrained quadratic minimum

[
d^2_{j,-} = rac{(mu_j-ell_j)^2}{Sigma_{jj}}.
]

Therefore every point in that outside halfspace satisfies

[
g(x)le
alphaexp!left[-rac12 d^2_{j,-}ight].
]

Likewise for (x_jge u_j),

[
d^2_{j,+} = rac{(u_j-mu_j)^2}{Sigma_{jj}}.
]

If the mean is already inside the queried outside halfspace, the conservative distance is zero and the bound is simply (alpha).

## Edited-field certificate

For each of the six outside halfspaces (h), define

[
B_h =
sum_{iin M}
left(
T_h(g_i^0)+T_h(g_i^1)
ight),
]

where (T_h(g)) is the corresponding closed-form Gaussian tail upper bound.

Every (x
otinOmega) belongs to at least one of those six halfspaces. Hence

[
oxed{
sup_{x
otinOmega}|ho_1(x)-ho_0(x)|
le
max_h B_h
}
]

under the density-field model above.

This certificate is:
- independent of Gaussian primitive ordering;
- unaffected by unchanged primitives;
- deterministic;
- inexpensive: six scalar tail evaluations per changed Gaussian state;
- directly tunable through a boundary margin.

## What this does NOT yet certify

This is **not yet a full 3DGS rendered-color certificate**. Standard splatting uses projection, depth ordering and nonlinear transmittance. A density-field locality theorem does not automatically imply an image-space RGB bound.

It also does not declare two split/merge representations geometrically equivalent. It certifies only the field contribution of the explicitly modified primitives outside a chosen spatial edit domain.

## Current empirical sanity probe

A synthetic probe sampled anisotropic Gaussian edits inside a 1 m box and tested 40,000 outside points per trial. Across margins 0.05–0.25 scene units and five seeds, no sampled point exceeded the analytic face-wise bound.

The face-wise bound is conservative but becomes substantially tighter as edited primitives lie farther from the edit boundary. Median bound/observed-max ratios in the exploratory probe were approximately:

| Interior margin | bound / sampled max |
|---:|---:|
| 0.05 | 17.15× |
| 0.10 | 8.82× |
| 0.15 | 7.78× |
| 0.20 | 4.52× |
| 0.25 | 3.94× |

The absence of sampled violations is only a sanity check; validity comes from the inequality above, not Monte Carlo sampling.

## Immediate attacks required

1. Generalize from AABB to oriented boxes / convex edit volumes.
2. Derive tighter change bounds using parameter deltas rather than old+new triangle inequality.
3. Connect density disturbance to an occupancy/surface displacement statement under regularity assumptions.
4. Determine whether a projected screen-space analogue can bound alpha/transmittance changes.
5. Compare against simple hard-freeze / bounding-box editing baselines on EditBench3D-style tasks.
6. Search specifically for prior work providing certified non-target 3DGS edit bounds.

If prior art already contains this certificate, kill the novelty claim and retain it only as engineering.
