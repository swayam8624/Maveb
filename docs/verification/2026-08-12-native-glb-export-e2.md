# 2026-08-12 native static GLB export evidence

This tranche establishes an E2 native publication boundary for validated static `MeshAsset` data.
It is fixture evidence, not a claim that AETHER can ingest Apple's USDZ output without Blender.

## Contract

`GltfExporter::writeGlb` publishes one deterministic glTF 2.0 binary file through atomic sibling
replacement. The supported static subset preserves:

- indexed triangle primitives and flat world-space instances;
- positions, normals, tangents, primary UVs, and optional RGB vertex colors;
- metallic-roughness factors, base-color/metallic-roughness/normal/emissive textures, samplers,
  alpha modes, double-sided state, and per-slot `KHR_texture_transform`;
- PNG and JPEG source bytes embedded as GLB buffer views.

Animation, skins, morph targets, non-triangle topology, invalid indices, degenerate triangles,
non-finite or singular transforms, non-opaque vertex-color alpha, unsupported image encodings, and
configured resource-limit overflow return structured errors. They are not silently flattened.

## Verification

The C++ test constructs a two-instance textured asset with RGB vertex colors, writes it twice,
requires byte-identical output, and re-imports it through the strict production loader. It checks
geometry counts, resources, transforms, UV transforms, and vertex colors, then exercises animation,
degenerate-index, and invalid-image rejection.

The `AetherNativeGlbExport` command test treats the CLI as a black box. It verifies its JSON report
and SHA-256, byte-for-byte determinism, valid GLB chunk lengths, embedded buffers/images, required
attributes and texture-transform declaration, dry-run destination non-mutation and cleanup, plus
structured animation rejection with no partial output.

Commands used for this evidence record:

```bash
cmake --preset ci
cmake --build --preset ci -j 8
ctest --preset ci --output-on-failure

cmake --preset sanitizer
cmake --build --preset sanitizer -j 8
ctest --test-dir build/sanitizer --output-on-failure
```

The exact executed results are recorded in the tranche handoff. A real photogrammetry artifact and
native USDZ ingestion are intentionally outside this E2 fixture gate.
