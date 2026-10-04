# Sparse CPU TSDF reference evidence — E2

Date: 2026-08-12

This record establishes a deterministic block-sparse CPU fusion reference on top of the R1 dense
oracle. It does not claim real-time Metal fusion, incremental meshing, or improved real-capture
accuracy.

## Implemented proof

- A room-scale logical grid can be created without allocating its dimension product.
- Valid depth rays are clipped to the logical block AABB and conservatively cover the projected
  pixel footprint, free-space segment, and truncation band.
- Fusion exactly preserves the dense oracle's projection, confidence, signed-distance, saturation,
  color, and observation equations.
- Candidate and resident blocks are deterministic; frame updates are transactional and dirty-block
  acknowledgement is explicit.
- Disjoint rays, non-finite footprints, hostile block sizes, candidate exhaustion, resident
  exhaustion, extraction exhaustion, and arithmetic-overflow configurations fail without partial
  mutation.
- Extraction produces the exact resolved dense-oracle mesh over a bounded active-span snapshot.

## Deterministic measurements

The translated and 12-degree yaw-rotated plane fixture observes 3,712 voxels in both dense and
sparse volumes. All voxel records agree exactly. Resolved extraction agrees exactly at 882 vertices
and 1,680 triangles while the sparse volume owns 106 four-cubed blocks.

The room fixture declares 1,003,003,001 logical voxels but allocates 1,102 eight-cubed blocks:
564,224 resident voxels and 13,541,376 bytes of voxel payload. That leaves
99.943746529228989 percent of the logical domain unallocated. The generated report is committed at
`benchmarks/evidence/r5-sparse-cpu-m2-pro-2026-08-12.json` and CTest requires byte-for-byte equality.

## Verification commands and actual results

```text
cmake --build --preset ci -j 8
ctest --preset ci --output-on-failure
Result: build passed; 13/13 tests passed

cmake --build --preset sanitizer -j 8
ctest --test-dir build/sanitizer --output-on-failure
Result: build passed; 13/13 tests passed under the sanitizer configuration

/opt/homebrew/opt/llvm/bin/clang-format --dry-run --Werror \
  engine/reconstruction/include/aether/reconstruction/SparseTsdfVolume.hpp \
  engine/reconstruction/src/SparseTsdfVolume.cpp tests/SparseTsdfTests.cpp
Result: passed

/opt/homebrew/opt/llvm/bin/clang-tidy -p build/ci --warnings-as-errors='*' \
  engine/reconstruction/src/SparseTsdfVolume.cpp tests/SparseTsdfTests.cpp \
  --extra-arg=-isysroot --extra-arg="$(xcrun --sdk macosx --show-sdk-path)"
Result: passed; dependency/system warnings were suppressed by clang-tidy

../Maveb/.aether-deps/proxy-venv/bin/python \
  -m unittest discover -s benchmarks/tests -p 'test_*.py'
Result: 16/16 passed

git diff --check
Result: passed
```

The review worktree intentionally does not contain private `.aether-deps` binaries. The MavebBench
tests therefore used the existing pinned Python 3.12.13 environment from the primary development
checkout while executing the test sources from this worktree.

## Remaining R5 work

The extraction path still densifies the allocated block span, so widely separated resident blocks
can exceed the explicit extraction budget even when their payload is small. R5 remains open for
halo-consistent incremental block meshing, snapshot isolation, sparse Metal allocation/fusion,
memory-pressure persistence and eviction, real-capture CPU/GPU agreement, and performance evidence.
