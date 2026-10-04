# Proxy geometry generation

`aether-proxy` converts the quality-filtered points in a COLMAP `points3D.txt` model into a coarse
triangle proxy. The proxy is for depth, shadow receiving, alignment, collision cleanup, and editor
inspection; it is not presented as recovered photogrammetric surface truth.

The AETHER-owned pipeline strictly parses bounded COLMAP records, rejects duplicate/non-finite
points and malformed tracks, filters by reprojection error and unique track length, voxelizes the
accepted cloud, estimates and consistently orients normals, runs Open3D Poisson reconstruction,
removes low-density and out-of-bounds surface, repairs basic topology, and applies a triangle budget.
Poisson runs single-threaded by default and Open3D's random seed is fixed. Repeated runs over the
same fixture must produce the same binary PLY hash on the supported environment.

```bash
.aether-deps/bin/aether-proxy job/sparse/0-text/points3D.txt \
  --output job/proxy/proxy.ply --report job/proxy/proxy.json --json
```

Configuration is an optional schema-v1 JSON document. Unknown fields and unsafe ranges are hard
errors. The atomic report records tool/Open3D versions, complete effective configuration, input and
output SHA-256 hashes, accepted point count, effective voxel size, spatial extent, density cutoff,
and final vertex/triangle counts. Outputs are first written beside their destination and atomically
renamed, so cancellation or failure cannot masquerade as a completed proxy.
