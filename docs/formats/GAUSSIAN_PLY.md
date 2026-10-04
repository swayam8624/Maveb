# Standard 3DGS PLY import contract

AETHER accepts PLY 1.0 in ASCII or binary-little-endian form. The file must contain exactly one
populated `vertex` element and no populated face or auxiliary elements. Vertex list properties,
duplicate properties, big-endian payloads, non-finite values, zero quaternions, unsafe log scales,
trailing payload data, and inconsistent binary sizes are rejected before renderer allocation.

Required scalar properties are:

- `x`, `y`, `z`
- `f_dc_0`, `f_dc_1`, `f_dc_2`
- `opacity`
- `scale_0`, `scale_1`, `scale_2`
- `rot_0`, `rot_1`, `rot_2`, `rot_3`

`f_rest_N` properties are optional, but when present they must be dense and encode a complete SH
degree: 9 values for degree 1, 24 for degree 2, or 45 for degree 3. Unregistered scalar properties
are skipped with conversion diagnostics. Rotations are normalized on import in `(w, x, y, z)`
order. Higher-order coefficients retain GraphDECO's channel-major PLY order (15 red, 15 green, 15
blue at degree 3); both CPU and Metal evaluators interpret that order through degree 3. Scale and
opacity remain in log/logit space to preserve the trained representation.

The default hostile-input limits are a 16 GiB file, 1 MiB header, 256 vertex properties, and 100
million Gaussians. Callers may reduce every limit. A deterministic anisotropic CPU rasterizer is the
correctness oracle for the Metal path; it evaluates projected covariance, front-to-back alpha,
first-hit depth, and dominant source ID.
