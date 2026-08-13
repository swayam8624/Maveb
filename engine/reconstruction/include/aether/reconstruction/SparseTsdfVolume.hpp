#pragma once

#include <aether/reconstruction/DenseTsdfVolume.hpp>

#include <compare>
#include <cstddef>
#include <cstdint>
#include <map>
#include <optional>
#include <set>
#include <vector>

namespace aether::reconstruction {

struct TsdfBlockCoordinate final {
    std::uint32_t x{};
    std::uint32_t y{};
    std::uint32_t z{};
    auto operator<=>(const TsdfBlockCoordinate&) const = default;
};

struct SparseTsdfConfig final {
    /// Logical grid geometry and fusion parameters. Unlike DenseTsdfVolume, the dimension product
    /// is not allocated and may describe a room-scale grid.
    DenseTsdfConfig volume;
    std::uint32_t blockResolution{8};
    std::size_t maximumBlocks{65'536};
    std::size_t maximumCandidateBlocksPerFrame{131'072};
    /// Exact production extraction currently densifies only the allocated bounding box and fails
    /// before exceeding this explicit oracle budget. Incremental block meshing is the next backend.
    std::size_t maximumExtractionVoxels{64ULL * 1024ULL * 1024ULL};
};

struct SparseTsdfStatistics final {
    std::size_t allocatedBlocks{};
    std::size_t allocatedVoxels{};
    std::size_t observedVoxels{};
    std::size_t voxelPayloadBytes{};
    std::size_t integratedFrames{};
    std::size_t lastFrameCandidateBlocks{};
    std::size_t lastFrameVoxelUpdates{};
    std::size_t dirtyBlocks{};
};

/// Deterministic block-sparse CPU TSDF reference. Camera coordinates use +Z forward.
class SparseTsdfVolume final : public IVolumeFusion, public IMeshExtractor {
  public:
    /// Input: finite metric grid parameters and explicit resident/candidate/extraction budgets.
    /// Output: an empty sparse volume; no logical voxel storage is allocated at creation.
    /// Task: validate a room-scale logical domain independently from its resident block count.
    static Result<SparseTsdfVolume> create(SparseTsdfConfig config);

    /// Input: validated sparse-grid parameters, calibrated metric depth, and an accepted pose.
    /// Output: the deterministic lexicographically ordered block set whose voxels may be updated.
    /// Task: share the CPU reference's conservative ray/footprint allocation contract with Metal
    /// backends without exposing or duplicating the fusion equations.
    static Result<std::vector<TsdfBlockCoordinate>>
    candidateBlocks(const SparseTsdfConfig& config, const capture::CapturePacket& packet,
                    const PoseEstimate& pose, const DepthObservation& depth);

    /// Input: calibrated metric depth and an accepted metric camera pose.
    /// Output: one transactional update of only blocks intersecting valid depth-ray free space and
    /// the truncation band. Failure leaves all previously resident blocks unchanged.
    /// Task: preserve DenseTsdfVolume's nearest-pixel projection, confidence, distance, weight,
    /// color, and saturation equations while avoiding allocation of the full logical AABB.
    Result<void> integrate(const capture::CapturePacket& packet, const PoseEstimate& pose,
                           const DepthObservation& depth) override;

    /// Output: the exact resolved dense-oracle extractor over the allocated block bounding box.
    /// Failure: an empty surface or an active span beyond maximumExtractionVoxels is explicit.
    Result<mesh::MeshAsset> extractMesh() const override;

    [[nodiscard]] const SparseTsdfConfig& config() const noexcept {
        return config_;
    }
    [[nodiscard]] SparseTsdfStatistics statistics() const noexcept;
    [[nodiscard]] std::optional<TsdfVoxel> voxel(std::uint32_t x, std::uint32_t y,
                                                 std::uint32_t z) const noexcept;
    [[nodiscard]] std::vector<TsdfBlockCoordinate> dirtyBlocks() const;
    void clearDirtyBlocks() noexcept {
        dirtyBlocks_.clear();
    }

  private:
    using Block = std::vector<TsdfVoxel>;

    explicit SparseTsdfVolume(SparseTsdfConfig config);
    [[nodiscard]] std::size_t blockVoxelCount() const noexcept;
    [[nodiscard]] std::size_t localIndex(std::uint32_t x, std::uint32_t y,
                                         std::uint32_t z) const noexcept;

    SparseTsdfConfig config_;
    std::map<TsdfBlockCoordinate, Block> blocks_;
    std::set<TsdfBlockCoordinate> dirtyBlocks_;
    std::size_t observedVoxels_{};
    std::size_t integratedFrames_{};
    std::size_t lastFrameCandidateBlocks_{};
    std::size_t lastFrameVoxelUpdates_{};
};

} // namespace aether::reconstruction
