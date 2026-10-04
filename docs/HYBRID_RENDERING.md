# Hybrid proxy and Gaussian depth

An optional canonical `proxy-mesh` package chunk is decoded under explicit vertex and triangle
limits before any GPU allocation. The renderer converts it into a fixed 32-byte shared CPU/MSL
vertex ABI, uploads private vertex and index buffers, and reports retained vertex/triangle counts.
Loading plain PLY or glTF clears the proxy state; a failed package load does not partially replace
the active scene.

Each frame clears and records a named **Proxy G-buffer Pass** before captured-world composition. It
writes Depth32F reverse-Z depth, RGBA16F encoded world normal plus reconstruction confidence,
R32Uint surface IDs, and RGBA16F temporal motion. Reconstructed winding is not trusted, so this
depth-support pass is intentionally two-sided. The proxy remains visually invisible.

The Gaussian composition pass compares its positive camera-space depth with proxy reverse-Z depth.
The acceptance band combines a 1 cm absolute term, 1.5 percent of proxy depth, and a conservative
low-confidence multiplier. A Gaussian beyond that band is suppressed. Within the band, Gaussian
appearance remains visible while the nearer proxy depth and motion stabilize later mesh occlusion.
Where no Gaussian survives, proxy depth and motion still populate the scene targets over the normal
background. Proxy IDs stay in a dedicated attachment and are available through `pickProxy`; they do
not collide with mesh entity IDs or Gaussian source IDs.

`AetherMetalTests` packages canonical Gaussian and proxy chunks at runtime, verifies retained proxy
dimensions, renders a zero-confidence foreground control, raises its confidence, and requires the
behind-surface Gaussian to disappear while proxy ID and temporal depth remain valid. Run it with Metal API and shader
validation as documented in [renderer golden artifacts](RENDER_GOLDENS.md).

This is not the complete Phase 5 claim. Multiple dynamic assets, proxy shadow-factor transfer,
collision queries, particles, reflections, and navigation remain separate gated work.

## Dynamic PBR attachment

A captured PLY or `.aether` scene may own one glTF/GLB attachment at a time. Studio persists its
path in project schema v4 and provides add, replace, and remove actions. Replacement uploads and
validates the entire glTF before publishing mesh, texture, material, skin, morph, animation, and
transform state as one transaction; a failed replacement leaves the current attachment and
captured-world resources untouched. Detach clears only dynamic state.

Dynamic entities use the existing production PBR, lighting, shadow-caster, animation, picking,
outliner, material, and transform paths. Their scene IDs carry a dedicated tag that `pickMesh`
validates and strips, so Gaussian source IDs cannot be mistaken for mesh entities. In hybrid Studio
picking, a visible tagged mesh wins; otherwise selection falls through to the Gaussian ID target.

The Metal integration fixture places a dynamic triangle in front of a confident proxy, requires a
tagged mesh pick, then moves the same entity behind the proxy and requires the pick to disappear.
The resulting `hybrid-mesh-front` and `hybrid-mesh-behind` artifacts prove that dynamic PBR draws
consume the same reverse-Z depth established by captured-world composition.
