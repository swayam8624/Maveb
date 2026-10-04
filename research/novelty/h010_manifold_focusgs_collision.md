# H010 Novelty Collision Audit — Manifold-GS and FocusGS

**Date:** 2026-09-20
**Candidate:** H010 Gaussian tail locality certificate
**Decision:** SURVIVES NARROWLY; novelty remains unverified.

## Candidate H010

For changed Gaussian primitives only, H010 derives a uniform bound on additive 3D Gaussian density-field disturbance outside an arbitrary allowed edit volume. For an AABB, each outside halfspace admits a closed-form Gaussian tail maximum. Summing old/new tails over changed primitives and taking the maximum over the six outside halfspaces yields

[
sup_{x
otinOmega}left|ho_1(x)-ho_0(x)ight|
le max_h B_h.
]

The claim is intentionally narrow:
- it is a field-disturbance certificate;
- it is not yet a rendered RGB/transmittance guarantee;
- it does not claim Gaussian indices are refinement-stable;
- it does not itself provide an editing operator.

## Collision 1 — Manifold-GS

Manifold-GS (arXiv 2608.00214) is a major neighboring work. It:
- separates appearance opacity from geometric quadrature mass;
- models surface-like Gaussians as a discrete unoriented varifold;
- transports mass conservatively through refinement;
- exports confidence-certified open surface patches;
- preserves source bindings;
- reports zero patch-defined edit leakage on its frozen DTU asset benchmark.

### Overlap

Both works use the language and purpose of **certification** around Gaussian assets and local editing. Both care about refinement/adaptive primitives and non-target effects.

### Distinction presently supported

Manifold-GS certifies **which geometric surface patches can be exported and manipulated as a structured hybrid asset**, including refinement-conservative geometric mass and source bindings.

H010 instead certifies an **upper bound on the contribution of explicitly changed radiance/density primitives outside a spatial edit domain**, directly in the Gaussian field.

These are different mathematical objects:
- Manifold-GS: surface quadrature / varifold mass / realizability / patch-source binding.
- H010: Gaussian tail supremum / non-target field disturbance.

These are also different failure questions:
- Manifold-GS asks whether a part of an adaptive Gaussian model is trustworthy enough to become an editable geometric patch.
- H010 asks, given a set of primitive parameter changes, how much those changes can affect the field outside the authorized domain.

### Threat level

**HIGH.** A reviewer can reasonably group both under “certified editable Gaussian assets.” H010 must therefore demonstrate a capability that Manifold-GS does not already imply: a user-selectable spatial tolerance certificate over arbitrary edits, preferably extended to rendered alpha/RGB or surface displacement.

If H010 remains only an additive-density inequality, it may be mathematically correct but too small relative to Manifold-GS.

## Collision 2 — FocusGS

FocusGS (arXiv 2607.28834) freezes the base asset and represents repair/editing as composite spatial delta layers. Deterministic editing uses erase-insert factorization. Retrieved descriptions also state that protected-region penalties discourage new Gaussians from bleeding outside the target area.

### Overlap

FocusGS already occupies:
- local repair of trained Gaussian assets;
- deterministic local editing;
- spatial delta terminology;
- frozen non-target base content;
- suppression of effects outside target regions.

### Distinction presently supported

FocusGS is an **editing/maintenance operator** whose locality is enforced by construction, masks and optimization losses.

H010 is a **post/pre-flight analytic certificate** that can in principle be applied to any editing operator and reject an edit whose predicted outside-domain disturbance exceeds a chosen threshold.

Therefore the safe research framing is not “MAVEB performs deterministic local editing.” That is occupied.

The candidate research question is:

> Can arbitrary Gaussian edits be accompanied by a cheap, representation-native certificate that upper-bounds non-target physical-field disturbance, independently of the optimizer used to produce the edit?

### Threat level

**HIGH but survivable.** H010 must be evaluated on top of or against a FocusGS-like editing operator. If freezing/protected masks already make empirical leakage effectively zero and H010 never rejects a meaningful failure, the certificate has little practical value and should be killed.

## New required novelty gates

H010 cannot be promoted further until all of these pass:

1. **Exact-prior-art gate:** find no earlier method giving the same Gaussian tail / halfspace / outside-volume disturbance certificate.
2. **Tightness gate:** practical edit margins yield bounds sufficiently tight to distinguish safe from unsafe edits.
3. **Failure-prediction gate:** certificate value predicts actual non-target field/render/surface disturbance better than simple margin, max-scale, opacity or support-radius heuristics.
4. **Operator-agnostic gate:** works across at least two distinct edit mechanisms, one of which should be a frozen/spatial-delta style baseline.
5. **Rendering relevance gate:** derive or empirically establish a useful relation to alpha/transmittance/RGB change, or a surface-level geometric quantity.
6. **Manifold-GS distinction gate:** demonstrate a case where patch/source certification and outside-field disturbance certification answer different questions and H010 adds actionable information.
7. **Ablation gate:** removing the certificate causes unsafe edits to pass or forces much more conservative hard freezing.

## Immediate mathematical extension

For a general halfspace

[
H^- = {x:a^Txle b},
]

when the Gaussian mean lies on the interior side of the allowed region and the outside halfspace begins at the boundary, the constrained Mahalanobis distance to the plane is

[
d^2 = rac{(a^Tmu-b)^2}{a^TSigma a}.
]

Therefore the tail maximum in that halfspace is

[
T_H(g)=alphaexp(-d^2/2).
]

For any convex polytope represented as an intersection of halfspaces, the complement is the union of the corresponding outside halfspaces. The AABB result thus generalizes naturally to oriented boxes and arbitrary convex edit volumes.

This is the next theory implementation target.

## Current verdict

**Do not kill H010 yet. Do not call it novel yet.**

Manifold-GS and FocusGS force the contribution to become much more precise:

> not certified assets, not local Gaussian editing, not spatial deltas — but an operator-agnostic quantitative certificate on non-target field influence of a proposed Gaussian edit.
