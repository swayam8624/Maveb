#pragma once

#include <aether/metal/MetalPtr.hpp>
#include <aether/reconstruction/SparseTsdfVolume.hpp>

#include <Metal/Metal.hpp>

#include <cstddef>
#include <cstdint>
#include <map>
#include <memory>
#include <set>
#include <vector>

namespace aether::metal {

struct SparseMetalTsdfLimits final {
    std::size_t maximumFramePixels{16ULL * 1024ULL * 1024ULL};
    std::size_t maximumResidentBytes{1ULL * 1024ULL * 1024ULL * 1024ULL};
    std::size_t maximumScratchBytes{512ULL * 1024ULL * 1024ULL};
};

struct SparseMetalTsdfStatistics final {
    std::size_t residentBlocks{};
    std::size_t residentVoxels{};
    std::size_t observedVoxels{};
    std::size_t residentPayloadBytes{};
    std::size_t reservedPayloadBytes{};
    std::size_t integratedFrames{};
    std::size_t lastFrameCandidateBlocks{};
    std::size_t lastFrameVoxelUpdates{};
    std::size_t dirtyBlocks{};
    std::uint64_t generation{};
};

using SparseMetalTsdfBlockSnapshot = reconstruction::SparseTsdfBlockSnapshot;
using SparseMetalTsdfSnapshot = reconstruction::SparseTsdfSnapshot;

/// Metal 3 sparse-block TSDF fusion backend. Candidate allocation remains deterministic on the
/// host while all per-voxel admission, projection, confidence, color, and weighted fusion execute
/// on the GPU. Camera coordinates use +Z forward.
class SparseMetalTsdfVolume final : public reconstruction::IVolumeFusion {
  public:
    /// Input: an Apple-silicon Metal device, offline shader library, and validated sparse config.
    /// Output: an empty GPU volume with no resident voxel allocation until the first accepted
    /// frame. Failure: missing kernels, invalid config, or command-queue creation is explicit.
    [[nodiscard]] static Result<std::unique_ptr<SparseMetalTsdfVolume>>
    create(MTL::Device* device, MTL::Library* library, reconstruction::SparseTsdfConfig config,
           SparseMetalTsdfLimits limits = {});

    /// Input: calibrated CPU capture planes, a metric pose, and a metric depth observation.
    /// Output: synchronously completed GPU fusion into deterministic sparse block slots.
    /// Task: classify candidate voxels before allocation, stage updates in scratch storage, and
    /// publish only after the fusion command succeeds. CPU validation/budget failures do not alter
    /// resident blocks. A Metal execution failure invalidates the current call and is reported.
    [[nodiscard]] Result<void> integrate(const capture::CapturePacket& packet,
                                         const reconstruction::PoseEstimate& pose,
                                         const reconstruction::DepthObservation& depth) override;

    /// Output: an immutable CPU copy of every resident block at one completed generation.
    /// Task: provide an extraction-safe boundary without exposing live Metal resources.
    [[nodiscard]] Result<SparseMetalTsdfSnapshot> snapshot() const;

    [[nodiscard]] const reconstruction::SparseTsdfConfig& config() const noexcept {
        return config_;
    }
    [[nodiscard]] SparseMetalTsdfStatistics statistics() const noexcept;
    [[nodiscard]] std::vector<reconstruction::TsdfBlockCoordinate> dirtyBlocks() const;
    void clearDirtyBlocks() noexcept {
        dirtyBlocks_.clear();
    }

  private:
    SparseMetalTsdfVolume(MTL::Device* device, reconstruction::SparseTsdfConfig config,
                          SparseMetalTsdfLimits limits);
    [[nodiscard]] Result<void> buildPipelines(MTL::Library* library);
    [[nodiscard]] Result<void> ensureResidentCapacity(std::size_t requiredBlocks);

    reconstruction::SparseTsdfConfig config_;
    SparseMetalTsdfLimits limits_;
    MetalPtr<MTL::Device> device_;
    MetalPtr<MTL::CommandQueue> commandQueue_;
    MetalPtr<MTL::ComputePipelineState> classifyPipeline_;
    MetalPtr<MTL::ComputePipelineState> initializePipeline_;
    MetalPtr<MTL::ComputePipelineState> integratePipeline_;
    MetalPtr<MTL::Buffer> residentVoxels_;
    std::map<reconstruction::TsdfBlockCoordinate, std::uint32_t> blockSlots_;
    std::vector<reconstruction::TsdfBlockCoordinate> slotCoordinates_;
    std::set<reconstruction::TsdfBlockCoordinate> dirtyBlocks_;
    std::size_t residentCapacityBlocks_{};
    std::size_t observedVoxels_{};
    std::size_t integratedFrames_{};
    std::size_t lastFrameCandidateBlocks_{};
    std::size_t lastFrameVoxelUpdates_{};
    std::uint64_t generation_{};
};

} // namespace aether::metal
