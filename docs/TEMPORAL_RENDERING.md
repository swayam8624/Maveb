# Temporal rendering and bloom

The mesh renderer uses an eight-sample Halton `(2,3)` camera jitter shared with the Gaussian
projection center. A full-resolution temporal resolve runs in linear HDR before exposure and tone
mapping. It ping-pongs RGBA16 color and R32 depth histories and consumes a full-resolution RGBA16
motion target containing current-minus-previous UV, previous reverse-Z depth, and validity. It
rejects out-of-bounds and depth-discontinuous history, clamps retained history to the current 3x3
color neighborhood, and uses a 90 percent history weight only when validation succeeds.

History is invalidated on target resize, scene replacement, animation selection or seek, lighting
or IBL replacement, first frame, and large camera-matrix discontinuities. PBR computes motion from
the previous jittered camera and previous entity model transform, covering continuous camera and
rigid editor/entity motion. Previous transforms advance only after frame encoding, and a bounded
one-texel diagnostic readback verifies signed X motion and validity after a known translation.
Skinned and morphed draws bind separate prior joint palettes and prior morph weights. The PBR vertex
path evaluates both current and previous positions in morph-before-skin order, while shadow passes
continue consuming only the current bindings. Palette upload preflight accounts for both copies,
prior scene-node worlds advance after encoding, and a real skinned frame runs under Metal API and
shader validation.

Gaussian composition converts the rasterizer's front-contributor positive camera depth into the
same infinite-projection reverse-Z depth used by meshes. It writes Gaussian source IDs and depth
into the shared scene targets, reconstructs world position with the inverse current jittered
view-projection, and projects it through the previous jittered view-projection to emit camera-motion
vectors and previous reverse-Z depth. Invalid, empty, sub-threshold, offscreen, or first-frame
samples explicitly carry zero validity and do not accumulate history. This also establishes shared
depth semantics for hybrid mesh/splat occlusion. A separate proxy pass writes reverse-Z depth,
world normal plus reconstruction confidence, surface IDs, and camera motion before composition.
When a proxy sample is closer than a Gaussian, the visible Gaussian color may be anchored to proxy
depth within a confidence-scaled tolerance; a Gaussian defensibly behind that tolerance is removed.
Proxy depth and motion remain present even where no Gaussian survives, so later dynamic meshes see
a stable captured-world occluder. Proxy IDs remain isolated from mesh and Gaussian selection IDs.

Bloom runs after temporal resolve and before presentation. A soft-knee thresholded nine-tap
downsample produces a half-resolution buffer, followed by a second filtered quarter-resolution
level. Both levels are reconstructed with linear sampling and added at conservative intensity in
HDR before exposure and the ACES-style curve. All targets are private, resize with the drawable,
carry GPU labels, and have fixed dimensions derived from the full-resolution target.

The Metal integration test submits two real 320x180 MTK frames. The first exercises history
initialization and the second exercises valid history reads; both also execute local and directional
shadows, bloom, and presentation. The test is runnable with `MTL_DEBUG_LAYER=1` and
`MTL_SHADER_VALIDATION=1`.

The renderer also exposes an opt-in one-shot frame capture. Studio configures its MTK view as
non-framebuffer-only so drawable readback is legal under Metal validation. A request inserts a drawable-to-shared
buffer blit after presentation encoding and copies compact BGRA8 rows only from the command-buffer
completion callback. Normal frames perform no readback or allocation. The integration test captures
the second temporal frame and enforces a checked luminance interval, bright-pixel population, exact
dimensions, compact byte count, and fully opaque presentation. These bounded metrics tolerate minor
GPU-family rounding while detecting missing geometry, broken lighting, black output, bloom runaway,
incorrect alpha, and presentation regressions.

Pipeline binary archives are keyed by the SHA-256 of the complete offline `.metallib`. Shader or ABI
changes therefore create a new archive instead of asking Metal to deserialize an incompatible cached
pipeline. Archives are published through uniquely named temporary files plus a SHA-256 sidecar; an
unverified or torn cache is ignored. Metal API/GPU validation deliberately starts from an empty
archive because Apple's validation layer can crash while deserializing an otherwise recoverable
cache. Normal runs cover both first creation and verified subsequent loading.
