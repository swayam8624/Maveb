#pragma once

#include <aether/reconstruction/DenseTsdfVolume.hpp>

#include <array>
#include <cstdint>
#include <span>

namespace aether::reconstruction {

/// Classic Lorensen-Cline case-table reference used to verify production extraction.
class ReferenceMarchingCubes final {
  public:
    using CaseTriangles = std::array<std::int8_t, 16>;

    /// Input: a classic 8-bit Marching Cubes case index.
    /// Output: edge indices grouped as triangles and terminated by -1.
    /// Task: expose the immutable reference topology for exhaustive parity tests.
    [[nodiscard]] static const CaseTriangles& caseTriangles(std::uint8_t caseIndex) noexcept;

    /// Input: a validated dense scalar field; negative samples are inside the surface.
    /// Output: an indexed mesh using only interpolated cube-edge vertices.
    /// Task: provide a deliberately simple correctness oracle, not the production ambiguity path.
    static Result<mesh::MeshAsset> extract(const DenseTsdfConfig& config,
                                           std::span<const TsdfVoxel> voxels);
};

} // namespace aether::reconstruction
