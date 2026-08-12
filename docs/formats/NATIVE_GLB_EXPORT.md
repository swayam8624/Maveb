# Native static GLB export

Maveb authors a deterministic, self-contained glTF 2 binary from its canonical `MeshAsset` without
launching Blender. This path is intended for reconstructed static surfaces, including the colored
proxy emitted by `aether-fuse` and future texture-baking outputs.

## Supported profile

The writer preserves:

- indexed triangle primitives with positions, unit normals, UVs, optional complete tangents, and
  optional RGB vertex colors;
- static scene instances and their affine world transforms while sharing primitive data;
- metallic-roughness materials, alpha mode, sidedness, emissive factors, all five core texture
  bindings, normal/occlusion factors, and `KHR_texture_transform`;
- per-texture filtering, mip filtering, and address modes; and
- embedded PNG or JPEG source images.

Material slot zero in `MeshAsset` is the engine's implicit default. Authored glTF materials begin at
slot one. Export rejects non-default data in slot zero so a material can never be silently lost.

The byte encoder writes attributes and indices in fixed order, uses fixed object names for generated
objects, and contains no timestamps or machine paths. Identical input and limits therefore produce
identical GLB bytes. File publication uses a sibling temporary file followed by atomic replacement;
a failed validation or write leaves an existing destination intact.

## Validation and limits

Before encoding, the writer enforces explicit limits for output bytes, images and image bytes,
primitives, instances, vertices, indices, and names. It rejects:

- empty or non-triangle primitives, invalid indices, degenerate triangles, and non-finite data;
- non-unit normals, partial tangents, invalid colors or PBR factors;
- singular, non-finite, or non-affine instance transforms;
- external image formats or mislabeled image bytes; and
- animation, skinning, and morph targets.

The last category is an intentional profile boundary. Static reconstruction export must fail rather
than discard behavior from a general animated asset.

## Command-line use

The recorded RGB-D oracle can now write either format from the same validated mesh:

```bash
build/debug/tools/aether-fuse/aether-fuse recorded-capture \
  --output proxy.glb --voxel 0.01 --truncation 0.04 --json
```

PLY remains available for interoperability and metric inspection. GLB adds compact binary geometry
and vertex colors and can be loaded directly by Maveb's existing glTF path.

This exporter does not parse USDZ. Apple's photogrammetry baseline still uses Blender for USDZ to
GLB conversion until a separately reviewed, production-capable USD ingestion path exists. Native
GLB authoring removes that dependency only for geometry and materials already represented by
Maveb's own `MeshAsset`.
