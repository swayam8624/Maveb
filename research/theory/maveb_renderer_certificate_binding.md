# Binding the Locality Certificate to MAVEB's Metal Gaussian Renderer

**Renderer baseline:** main @ `1d95c8f480fb2868d821fa107215311f1deab17c`  
**Shader:** `shaders/gaussian.metal`  
**Status:** theory-to-implementation audit, 2026-09-20

## Exact current alpha path

MAVEB's Metal projection converts the stored opacity logit to opacity with a sigmoid after clamping
the logit to ([-30,30]).

During Gaussian compositing, for projected conic distance (q_i(p)):

1. if (q_i(p) > 9), the Gaussian is skipped;
2. otherwise
   [
   \alpha_i(p)=\min(0.99, o_i e^{-q_i(p)/2});
   ]
3. if (alpha_i(p)<1/255), it is skipped;
4. otherwise its color contribution is
   [
   (1-O)\alpha_i c_i,
   ]
   where (O) is accumulated opacity;
5. compositing terminates after accumulated opacity exceeds 0.999.

Therefore the **implemented** effective alpha is

[
\tilde\alpha_i(p)=
\begin{cases}
0, & q_i(p)>9,\\
0, & \min(0.99,o_i e^{-q_i(p)/2})<1/255,\\
\min(0.99,o_i e^{-q_i(p)/2}), & \text{otherwise.}
\end{cases}
]

The implementation has finite support even though the mathematical Gaussian itself does not.

## Exact zero-influence certificate for protected pixels

Let (E_0) and (E_1) be the edited Gaussian set before and after an edit. Let (P) be a protected
pixel set in a fixed camera.

If

[
\tilde\alpha_i(p)=0
\quad \forall p\in P,\; i\in E_0\cup E_1,
]

then the edited subset is never evaluated as a contributing layer on any protected pixel.

Assuming all non-edited renderer inputs are unchanged, the ordinary Gaussian composite result on
those protected pixels is **bit-path identical with respect to the edited subset**: RGB, accumulated
opacity, Gaussian depth and dominant source ID cannot be changed by the edited splats because they
never enter the contribution path.

This is stronger than a small-loss regularizer, but it is finite-view and renderer-specific.

## Epsilon RGB certificate when support overlaps

When edited support reaches protected pixels, define

[
A_s(p)=1-\prod_{i\in E_s}(1-\tilde\alpha_{i,s}(p)),
\qquad s\in\{0,1\}.
]

MAVEB's spherical-harmonic color evaluation is clamped only from below:

[
c_i=\max(\operatorname{SH}_i(d)+0.5,0).
]

It is **not upper-clamped to 1**. Therefore the generic normalized-RGB assumption in the first
probe is insufficient for the actual HDR Gaussian pass.

For a concrete protected camera/pixel, let (C(p)) be a valid upper bound on the per-channel color
range over relevant old/new layers and fixed background/composite state. Then

[
\|R_0(p)-R_1(p)\|_\infty
\le C(p)\min(1,A_0(p)+A_1(p)).
]

A simpler but looser implementation may use one scene/view-wide (C_{max}) computed from the
actual projected colors.

## What is and is not certified

### Zero-support case
Potentially certifies, for the ordinary Gaussian composite pass on the protected pixels:

- RGB unchanged by edited splats;
- accumulated opacity unchanged by edited splats;
- Gaussian depth unchanged by edited splats;
- dominant Gaussian source ID unchanged by edited splats.

### Nonzero-support epsilon case
The current bound certifies **RGB only**.

It does **not** certify depth or source ID. Even a very small edited alpha can become the first
accepted Gaussian and change depth, or become the dominant contribution and change source ID.
Those are discontinuous outputs and need their own stronger conditions.

### Debug modes
MAVEB debug modes overwrite normal color/opacity semantics. The certificate must be evaluated for
the production rendering mode, not blindly applied to diagnostic outputs.

### Hybrid proxy/Gaussian composition
The existing proxy-depth suppression can only remove some Gaussian contributions, so a certificate
computed conservatively before proxy suppression may remain safe for the Gaussian contribution.
However the final hybrid output contract must be proved against the actual hybrid pass before any
end-to-end claim.

## Immediate implementation probe

Add a CPU certificate evaluator beside the existing Gaussian CPU oracle:

1. consume projected Gaussians from the exact same projection convention;
2. consume a protected pixel mask and edited source-ID/index set;
3. compute exact zero-support status and per-pixel (A_0+A_1);
4. compute a valid color-range bound from concrete projected SH colors;
5. emit max/mean bound, fraction of exactly protected pixels, and the worst responsible splats;
6. compare the predicted bound to the actual old/new Metal and CPU-oracle pixel differences.

### Kill condition

Kill this direction if real edits almost never admit useful protected pixels/cameras at practical
epsilon, or if a simple hard editing mask provides the same guarantee and utility without the
opacity-mass machinery.
