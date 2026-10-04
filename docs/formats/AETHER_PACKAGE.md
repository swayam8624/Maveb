# AETHER scene package v1

`.aether` is AETHER's random-access, little-endian scene container. All offsets and sizes are
unsigned integers. A reader must validate the complete package before allocating or decompressing a
chunk.

## Header (64 bytes)

| Offset | Bytes | Field |
|---:|---:|---|
| 0 | 8 | Magic: `AETHER` followed by two zero bytes |
| 8 | 2 | Major version (`1`) |
| 10 | 2 | Minor version (`0`) |
| 12 | 4 | Package feature flags; zero in v1 |
| 16 | 8 | Absolute chunk-table offset |
| 24 | 4 | Chunk count |
| 28 | 4 | Reserved; zero in v1 |
| 32 | 32 | SHA-256 of every byte following the header |

## Chunk table

The table contains one 64-byte entry per chunk. Entries are unique by type.

| Offset | Bytes | Field |
|---:|---:|---|
| 0 | 4 | Registered chunk type |
| 4 | 4 | Flags: bit 0 required, bit 1 Zstandard compressed |
| 8 | 8 | Absolute payload offset |
| 16 | 8 | Stored byte count |
| 24 | 8 | Uncompressed byte count |
| 32 | 32 | SHA-256 of the uncompressed payload |

Payloads begin on 64-byte boundaries. Unknown optional chunks are skipped. Unknown required chunks
produce a compatibility error. Default readers reject files larger than 64 GiB, chunks larger than
8 GiB, more than one million chunks, overlapping payload ranges, invalid hashes, and compressed
chunks whose expansion ratio exceeds 256:1.

## Unpacked development schema

`aether-pack` accepts a directory containing `metadata.json` and at least one primary scene
representation. A Gaussian scene supplies validated `base-gaussians.ply` or canonical
`base-gaussians.bin`. A Canonical Asset v1 scene supplies `canonical-asset.json`, a self-contained
metric GLB, calibrated camera JSON, and explicit uniform or per-vertex confidence. Gaussian and
canonical representations may coexist. PLY input is converted into the canonical little-endian
chunk during packing; existing binary chunks are decoded and validated before acceptance. The remaining
registered filenames are optional: `cameras.bin`, `material-gaussians.bin`, `residuals.bin`,
`cluster-hierarchy.bin`, `proxy-mesh.bin`, `textures.bin`, `collision.bin`, `thumbnail.bin`, and
`benchmark-path.json`.

Packages containing Canonical Asset chunks use package minor version `1.1`; Gaussian-only v1
packages remain `1.0`. The added registered chunk types are `canonical-asset` (12),
`canonical-mesh` (13), and `canonical-confidence` (14). A Canonical Asset profile requires all
three plus `cameras`; partial profiles are rejected by semantic inspection. The canonical mesh is
the editable high-quality surface. `proxy-mesh` remains a distinct simplified representation for
occlusion, collision, navigation, and shadow transfer.

An optional `proxy.ply` is treated like a source representation for `proxy-mesh.bin`. The packer
strictly accepts ASCII or binary-little-endian triangulated PLY with finite positions, nondegenerate
normals, bounded scalar/property counts, optional byte colors, and uint32-addressable indices. It
rejects polygons, duplicate fields, extra elements/payloads, degenerate faces, and hostile sizes.
Existing canonical proxy chunks are decoded and subjected to the same semantic validation.

The current writer is deterministic for identical source bytes and chunk order. It uses Zstandard
level 3 when compression is smaller and remains inside the reader's expansion-ratio limit; otherwise
the payload is stored verbatim. Output is written to a sibling temporary file and atomically renamed.

## Base-Gaussian chunk v1

The chunk begins with a 32-byte header: eight-byte `AETHGS` magic, major/minor `uint16` version,
`uint32` record stride, `uint64` record count, `uint32` SH degree, and a reserved `uint32`. Every
record is 256 bytes and stores little-endian float32 position, log scale, normalized `(w,x,y,z)`
rotation, opacity logit, three DC coefficients, 45 reserved/active higher-order SH coefficients, and
the active higher-order coefficient count. Remaining record bytes are zero padding. Readers validate
the exact payload size, SH degree/count agreement, finite values, safe scale range, and quaternion
normalization.

## Proxy-mesh chunk v1

The 32-byte header stores eight-byte `AETHPX` magic, major/minor `uint16` version, a `uint32`
32-byte vertex stride, `uint64` vertex count, and `uint64` index count. Each vertex stores float32
position, normalized float32 normal, float32 confidence in `[0,1]`, and packed RGBA8. The remaining
payload is a tightly packed little-endian uint32 triangle-index array. Readers enforce exact size,
allocation budgets, finite coordinate bounds, normalized normals, triangulation, in-range indices,
and nondegenerate index triples.

## Canonical Asset chunks v1

The `canonical-asset` chunk stores the validated source manifest. The `canonical-mesh` chunk stores
a complete glTF 2 GLB whose buffers and images are embedded; external URIs are forbidden. PBR
materials, UVs, and encoded texture images therefore remain native glTF data rather than a second
private texture format. `cameras` uses the compiler-independent `AETHCAM` camera-rig codec, and
`canonical-confidence` uses the `AETHCF` little-endian float32 codec with one value in `[0,1]` per
mesh vertex. See [Canonical Asset v1](CANONICAL_ASSET.md) for the unpacked schema and invariants.
