# HDR rendering contract

AETHER shades and composes the scene in a private `RGBA16Float` target. Mesh PBR output, emissive
values, Gaussian appearance, and the background stay linear and may exceed 1.0. A dedicated
presentation pass applies exposure in photographic stops and the ACES-style fitted curve exactly
once before writing linear display values to the sRGB drawable.

The scene owns a matching `Depth32Float` target cleared to `0.0` for reverse-Z. Both targets are
recreated atomically when drawable dimensions change and carry explicit labels for GPU capture.
Depth is stored because hybrid proxy/Gaussian composition and later temporal passes consume it.
The drawable pass no longer performs scene shading.

The Lighting workspace exposes exposure from -8 to +8 EV; the renderer clamps its public API to
-16 through +16 EV and rejects non-finite updates. Exposure does not modify light intensity or
material values.

Every statically declared PBR texture and sampler slot is bound. Missing material maps use labeled
1x1 white or tangent-space-normal fallback textures and a fallback sampler, while texture bitmasks
still prevent those values from affecting shading. This is required by Metal API validation even
when shader control flow does not sample a disabled map.

Verification for this slice includes offline shader compilation, ABI assertions, debug/CI/
sanitizer tests, and live textured-mesh and Gaussian Studio runs under `MTL_DEBUG_LAYER=1`. Those
runs produced no validation errors after the fallback bindings were added. HDR screenshot goldens,
bloom, TAA, and output transforms beyond the sRGB Studio viewport remain later gates.
