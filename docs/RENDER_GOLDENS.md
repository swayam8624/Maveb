# Renderer golden artifacts

`AetherMetalTests` produces isolated review artifacts in
`build/debug/test-artifacts/metal` for the final PBR frame, directional cascade zero, the populated
slice discovered across the deterministic local-light allocation, Gaussian scene composition,
foreground-proxy occlusion, and dynamic PBR geometry placed in front of and behind the proxy.
Every capture is a portable binary PPM accompanied by
a SHA-256 sidecar over the exact presented BGRA8 bytes.

The test does not require one cross-device hash. Apple GPU families and OS shader compilers may
legitimately differ by a few quantization steps, so release gates use bounded subsystem-specific
metrics while hashes provide exact provenance for a particular run. PBR checks dimensions,
opacity, mean luminance, and bright-pixel population. Shadow-map views require finite caster
coverage distinguishable from the exact `1.0` cleared depth, including valid perspective depths
near the light far plane. Gaussian composition requires an opaque visible center
contribution and separately agrees with the CPU reference rasterizer for color, depth, and IDs.
The proxy artifact requires a canonical foreground surface to retain its dedicated ID, emit valid
reverse-Z temporal data, and suppress a known behind-surface Gaussian by a bounded color margin.
The hybrid pair additionally requires a tagged dynamic entity to be selectable in front and fully
occluded behind the same proxy surface.

When a deliberate rendering change moves a metric outside its bound, inspect all four images,
record the machine, macOS version, GPU family, and shader-library hash, then update the bound in the
same change as the renderer modification. Never accept a new exact hash without visual review, and
never widen a bound merely to hide an unexplained regression.

Run the validated suite with:

```bash
cmake --build --preset debug
MTL_DEBUG_LAYER=1 MTL_SHADER_VALIDATION=1 ./build/debug/tests/AetherMetalTests
```
