# Alpha-Mass Render Locality Bound

**Status:** candidate theorem / engineering certificate; not yet a paper claim.
**Date:** 2026-09-20

## Setup

Consider ordinary front-to-back alpha compositing at one pixel. All unchanged layers and the background are fixed. Let (E) denote the subset of Gaussian layers allowed to change.

For edited-layer pixel alphas (alpha_i \in [0,1]), define the aggregate edited opacity mass

[
A(E) = 1 - \prod_{i\in E}(1-\alpha_i).
]

Assume every rendered color component and the background lie in a bounded interval of width (C). For normalized LDR RGB, (C=1).

## Single-state removal bound

Remove every layer in (E), preserving every unchanged layer. Insert the edited layers back in front-to-back depth order.

Inserting one layer with alpha (alpha), front transmittance (T\le1), layer color (c), and already-composited behind color (b), changes one channel by

[
T\alpha(c-b).
]

Because (|c-b|\le C), the magnitude is at most (CT\alpha).

For multiple edited layers, unchanged layers can only reduce transmittance. Ignoring that extra attenuation therefore gives a conservative telescoping upper bound

[
\left\|R(U\cup E)-R(U)\right\|_\infty
\le C\left(1-\prod_{i\in E}(1-\alpha_i)\right)
= C A(E).
]

## Two-state edit bound

Let (E_0) and (E_1) be the edited Gaussian state before and after an edit, while (U) is unchanged. By the triangle inequality through the rendering with the edited subset removed,

[
\left\|R(U\cup E_0)-R(U\cup E_1)\right\|_\infty
\le C(A(E_0)+A(E_1)).
]

For normalized pixels the trivial global range also gives

[
\left\|R_0-R_1\right\|_\infty
\le \min(1, A(E_0)+A(E_1)).
]

The edited primitives may reorder in depth relative to unchanged primitives; the argument compares each state independently with the common rendering in which the edited subset is removed.

## Why this could matter for MAVEB

Existing 3DGS editors often mask, anchor, freeze, or regularize non-target Gaussians. Those mechanisms seek locality empirically. This bound asks a different question:

> after restricting which Gaussians are editable, can MAVEB **certify** that their residual projected alpha influence on a protected pixel set is below an explicit epsilon?

For a finite camera/pixel protection set (P), compute

[
B_P = \max_{p\in P} C\min(1, A_{0,p}+A_{1,p}).
]

If (B_P\le\epsilon), the edit has an explicit off-target display-space error guarantee over that protected set under the stated renderer/color assumptions.

For a projected Gaussian,

[
\alpha_i(p) = o_i \exp\left(-\tfrac12 q_i(p)\right),
]

so the certificate is directly tied to opacity, projected covariance, and Mahalanobis distance from protected pixels.

## Cheap falsification result

The randomized v0 probe sampled 100,000 pairs of edited states with arbitrary edited-layer depth reordering, random unchanged layers, random colors/backgrounds, and a wide log-uniform alpha scale.

Observed bound violations: **0 / 100,000**.

The bound is conservative: median actual/bound ratio was about **0.088**, p95 about **0.284**. That is acceptable for a certificate only if real protected-region bounds remain small enough to be useful.

## Immediate attacks required

1. Reproduce the bound using MAVEB's exact Gaussian projection, opacity convention, cutoff, SH/color path, and alpha compositing.
2. Handle HDR/unclamped SH by recording a valid radiance/color span (C), rather than silently assuming ([0,1]).
3. Test real Gaussian scenes and authored edits; report the fraction of protected pixels/cameras that can actually be certified at useful epsilon.
4. Compare against a simpler hard support/mask rule.
5. Test edited Gaussian motion crossing depth order and entering/leaving tiles.
6. Test covariance/opacity growth, where the certificate should correctly become weaker.
7. Define the camera-set limitation honestly: a finite-view certificate is not automatically an all-view world-space guarantee.

If the real-scene certificate is almost always vacuous, kill this direction.
