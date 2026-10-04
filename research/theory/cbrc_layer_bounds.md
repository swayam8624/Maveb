# CBRC layer bounds — Gaussian rendering and temporal history

Status: first implementation-backed analytic layer bounds. These are machinery for CBRC, not standalone novelty claims.

## Gaussian edited-set pixel theorem

Fix one pixel. Let U be all unchanged Gaussian layers plus the background and let E be an edited set. Assume every RGB channel in U and E lies in [0,M]. Let the effective renderer alpha of edited layer i be a_i after the production distance cutoff, 0.99 clamp, and 1/255 rejection.

Define edited termination probability

A(E) = 1 - product_i (1-a_i).

Inserting E at arbitrary depths into the fixed unchanged stack changes the rendered pixel from R(U) by at most

||R(U+E)-R(U)||_inf <= M A(E).

Interpret alpha compositing probabilistically: A(E) is the probability that the ray terminates on an edited layer rather than following the unchanged/background outcome. On the complementary event, the output is exactly the unchanged outcome. Since two channel values in [0,M] differ by at most M, the expectation changes by at most M A(E).

For before/after edited sets E0,E1, triangle inequality through U yields

||R(U+E0)-R(U+E1)||_inf
 <= M min(1, A(E0)+A(E1)).

This covers direct edited color and the indirect effect of changed transmittance revealing/suppressing unchanged content.

### Production binding

The Metal compositor uses:

- squared Mahalanobis cutoff > 9 => absent;
- alpha = min(0.99, peakOpacity exp(-distance/2));
- alpha < 1/255 => absent;
- front-to-back contribution T alpha.

The C++ helper `effectiveGaussianRendererAlpha` mirrors those rules.

The renderer SH output is `max(SH(direction)+0.5,0)` and has no fixed upper clamp. Therefore the [0,M] condition cannot silently assume unit RGB. `gaussianRendererColorUpperBound` computes a conservative per-channel direction-independent cap from the primitive's finite SH coefficients; a scene/pixel certificate must include the maximum relevant unchanged Gaussian/background cap as well as edited primitives.

### Hard boundaries

If the identity of unchanged content is not actually unchanged, or if publication/index corruption can reorder/drop unrelated records, this theorem does not legalize approximation. Those dependencies remain HARD.

## Temporal resolve theorem

For a validation-stable pixel, production temporal resolve blends current color c and retained/clamped history h with weight w (currently 0.9 for valid history).

Let e_c bound current-color revision error, e_h bound history-sample revision error, and e_n bound motion of the current-neighborhood clamp interval endpoints.

Componentwise clamp is non-expansive in its sample and changes by at most the maximum movement among sample and interval endpoints, so

e_clamped_history <= max(e_h,e_n).

Therefore

e_out <= (1-w)e_c + w max(e_h,e_n).

If the validation decision can change across the revision—disocclusion, depth discontinuity, invalid reprojection, out-of-bounds transition, or another reject/accept discontinuity—CBRC does not use a soft gain. The affected history is HARD-invalidated.

With no further current disturbance and stable retention, old history error decays as

e_t <= w^t e_0.

## Research consequences

These two bounds create the first implementation-backed soft edges for the captured-world chain:

Gaussian revision -> rendered current color -> temporal history -> resolved image.

They must still be validated against the exact production projection/compositor and real frame replay. The randomized C++ tests attack algebraic violations; they do not replace end-to-end oracle comparison.
