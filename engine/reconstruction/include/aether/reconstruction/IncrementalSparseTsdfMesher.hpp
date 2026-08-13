#pragma once

#include <aether/reconstruction/SparseTsdfVolume.hpp>

#include <map>
#include <optional>
#include <span>
#include <vector>

namespace aether::reconstruction {

struct IncrementalSparseMesherConfig final {
    std::size_t maximumPatchesPerUpdate{16'384};
    std::size_t maximumPatchVoxels{64ULL * 1024ULL};
};

struct SparseMeshPatchUpdate final {
    TsdfBlockCoordinate coordinate;
    std::uint64_t generation{};
    /// Empty removes geometry previously published for this coordinate.
    std::optional<mesh::MeshPrimitive> primitive;
};

/// Deterministic incremental TSDF mesher. A patch owns cells whose minimum grid corner belongs to
/// its sparse block, reads the positive topology halo, and reads a symmetric gradient halo. Dirty
/// samples also invalidate the seven negative owner neighbours that can reference them.
class IncrementalSparseTsdfMesher final {
  public:
    static Result<IncrementalSparseTsdfMesher> create(IncrementalSparseMesherConfig config = {});

    /// Input: an immutable completed sparse snapshot and its dirty resident block coordinates.
    /// Output: replacement/removal patches tagged with the snapshot generation.
    /// Task: rebuild only affected cell owners transactionally; failure preserves the prior cache.
    Result<std::vector<SparseMeshPatchUpdate>>
    update(const SparseTsdfSnapshot& snapshot, std::span<const TsdfBlockCoordinate> dirtyBlocks);

    /// Output: the current deterministic patch set as one mesh asset without welding boundaries.
    [[nodiscard]] mesh::MeshAsset mesh() const;
    [[nodiscard]] std::size_t patchCount() const noexcept {
        return patches_.size();
    }
    [[nodiscard]] std::uint64_t generation() const noexcept {
        return generation_;
    }

  private:
    explicit IncrementalSparseTsdfMesher(IncrementalSparseMesherConfig config) : config_(config) {}

    IncrementalSparseMesherConfig config_;
    std::map<TsdfBlockCoordinate, mesh::MeshPrimitive> patches_;
    std::uint64_t generation_{};
};

} // namespace aether::reconstruction
