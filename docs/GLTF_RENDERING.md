# glTF rendering contract

AETHER loads glTF 2.0 through a bounded fastgltf adapter and uploads immutable geometry once.
Default-scene nodes produce lightweight instances, so repeated meshes share Metal vertex and index
buffers. Nested TRS transforms are composed as column-major matrices. Singular transforms,
multiple-parent hierarchies, invalid indices, and configured allocation-limit violations fail with
structured errors rather than reaching the GPU.

Opaque and masked instances render first with reverse-Z writes. Blended instances use read-only
depth and a stable far-to-near world-bounds ordering. Mirrored nodes reverse their front-face
winding. Normals and tangents use the inverse-transpose transform, including the tangent handedness
change under reflection.

Core metallic-roughness textures support independent `KHR_texture_transform` scale, rotation, and
offset for base color, metallic-roughness, normal, occlusion, and emissive slots. Only `TEXCOORD_0`
is currently accepted; a transform that overrides the coordinate set to another channel produces
an explicit compatibility error.

TRS animation channels support `STEP`, `LINEAR`, and `CUBICSPLINE`. Rotation uses quaternion slerp
for linear keys and normalized Hermite results for cubic keys. Sampling returns immutable local
snapshots, resolves the node hierarchy separately, and can clamp or loop. The renderer exposes clip
selection, play/pause, and seek controls and automatically plays the first clip after loading an
animated asset.

Skinning supports four `JOINTS_0`/`WEIGHTS_0` influences per vertex. Weights are finite,
non-negative, non-zero, and normalized during import. Joint indices are checked against the skin
used by every mesh instance. Inverse-bind matrices and joint-node references are bounded and
validated. Each frame builds position and inverse-transpose normal palettes from animated joint
world transforms; a scene whose palettes exceed the fixed frame upload budget fails at load time.

Morph targets support position, normal, and tangent deltas with up to 64 targets per primitive.
Mesh default weights and node overrides are retained per instance, while target-major immutable
delta buffers remain shared with geometry. Metal applies weighted morph deltas before joint
skinning. Animated morph-weight channels, secondary influence sets, animation blending, and
editor-facing timeline controls remain open Phase 2 work.
