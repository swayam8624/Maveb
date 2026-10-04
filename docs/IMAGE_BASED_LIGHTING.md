# Image-based lighting contract

AETHER preprocesses finite, non-negative, linear floating-point equirectangular environments into
the split-sum resources consumed by the PBR renderer:

- a diffuse cosine-convolved irradiance cube;
- a GGX-prefiltered specular cube mip chain from smooth to rough;
- a two-channel BRDF integration lookup table.

Preprocessing uses deterministic Hammersley samples. Dimensions, sample counts, source pixels, mip
progression, and total output texels are validated before allocation. Horizontally wrapped,
vertically clamped bilinear source sampling is shared with CPU reference tests. A constant HDR
environment is used as a strong invariant: irradiance becomes radiance times pi, while every
specular roughness level preserves the original radiance.

The public renderer upload API validates all face, mip, and LUT dimensions. It creates labeled
floating-point cube/LUT textures and a trilinear clamp sampler. PBR combines irradiance diffuse and
prefiltered specular using roughness-aware Fresnel and the split-sum LUT, then applies material
occlusion and an explicit IBL intensity. Direct clustered lighting remains independent.

Studio starts with a neutral fully bound environment so Metal validation never sees missing cube,
LUT, or sampler arguments. Production captures can replace it with preprocessed data without
rebuilding pipelines. Environment-file decoding, disk caching of preprocessed probes, editor probe
selection, and reflection-probe blending remain subsequent product work.

Verification includes deterministic constant-environment tests, exact output dimensions,
non-finite input rejection, texel-budget rejection, public Metal upload validation, offline shader
compilation, and a live textured scene under `MTL_DEBUG_LAYER=1` with no API errors.
