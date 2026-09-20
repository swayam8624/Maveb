#pragma once

#include <aether/core/Error.hpp>
#include <aether/gaussian/GaussianAsset.hpp>
#include <aether/gaussian/GaussianUpdatePlan.hpp>
#include <aether/metal/MetalPtr.hpp>
#include <shared/AetherShaderTypes.h>

#include <Metal/Metal.hpp>

#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <span>
#include <vector>

namespace aether::metal {

struct GaussianPipelineStatistics final {
    std::uint32_t visibleGaussians{};
    std::uint32_t tileEntries{};
    std::uint32_t overflowedEntries{};
    std::uint32_t earlyTerminations{};
};

struct GaussianPublicationStatistics final {
    std::size_t touchedRecords{};
    std::size_t contiguousRanges{};
    std::size_t touchedBytes{};
    std::size_t fullBufferBytes{};

    [[nodiscard]] double byteRatio() const noexcept {
        if (fullBufferBytes == 0)
            return 0.0;
        return static_cast<double>(touchedBytes) / static_cast<double>(fullBufferBytes);
    }
};

class GaussianPipeline final {
  public:
    /// Input: Metal 3 device, offline library, and an explicit tile-entry memory budget.
    /// Output: a complete projection/scan/radix/range/composite compute pipeline.
    /// Task: own the standard Gaussian GPU path without requiring 64-bit atomics.
    [[nodiscard]] static Result<std::unique_ptr<GaussianPipeline>>
    create(MTL::Device* device, MTL::Library* library,
           std::uint32_t maximumTileEntries = 4'194'304);

    /// Input: validated canonical Gaussian asset.
    /// Output: uploaded GPU representation with fixed shared CPU/MSL ABI.
    [[nodiscard]] Result<void> load(const gaussian::GaussianAsset& asset);

    /// Validates a source-order subset translation without mutating GPU-visible state.
    [[nodiscard]] Result<void>
    validateTranslation(std::span<const std::uint32_t> gaussianIndices,
                        simd_float3 translationDelta) const;

    /// Applies one metric translation to a unique subset of source-order Gaussian IDs.
    /// The shared GPU buffer is fully preflighted before mutation, so invalid IDs, duplicates, or
    /// non-finite resulting positions leave every primitive unchanged.
    [[nodiscard]] Result<void> translate(std::span<const std::uint32_t> gaussianIndices,
                                         simd_float3 translationDelta);

    /// Input: command buffer, calibrated camera, and writable color/depth/ID textures.
    /// Output: ordered compute work on the caller's command buffer.
    /// Task: render front-to-back splats and expose bounded overflow through counters.
    [[nodiscard]] Result<void> encode(MTL::CommandBuffer* commandBuffer,
                                      AetherGaussianCamera camera, MTL::Texture* color,
                                      MTL::Texture* depth, MTL::Texture* ids,
                                      std::size_t frameSlot);

    /// Call only after the encoded command buffer completes.
    [[nodiscard]] GaussianPipelineStatistics statistics() const noexcept;

    /// Logical bytes/ranges changed by the most recent local mutation.
    [[nodiscard]] GaussianPublicationStatistics publicationStatistics() const {
        std::scoped_lock lock(publicationMutex_);
        return lastPublicationStatistics_;
    }

    /// Actual bytes/ranges copied into the most recently recycled frame-slot source buffer.
    [[nodiscard]] GaussianPublicationStatistics framePublicationStatistics() const {
        std::scoped_lock lock(publicationMutex_);
        return lastFramePublicationStatistics_;
    }

  private:
    GaussianPipeline(MTL::Device* device, std::uint32_t maximumTileEntries);
    [[nodiscard]] Result<void> buildPipelines(MTL::Library* library);
    [[nodiscard]] Result<void> ensureTileRanges(std::uint32_t tileCount);
    [[nodiscard]] Result<void>
    validateTranslationLocked(std::span<const std::uint32_t> gaussianIndices,
                              simd_float3 translationDelta) const;
    [[nodiscard]] Result<void> publishFrameSlot(std::size_t frameSlot);
    void collectPublishedJournalLocked() noexcept;
    [[nodiscard]] Result<void>
    dispatch1D(MTL::CommandBuffer* commandBuffer, MTL::ComputePipelineState* pipeline,
               std::uint32_t threads, const char* label,
               const std::function<void(MTL::ComputeCommandEncoder*)>& bind) const;

    MetalPtr<MTL::Device> device_;
    std::uint32_t maximumTileEntries_{};
    static constexpr std::size_t gaussianSourceBufferCount_ = 3;

    struct PublicationPatch final {
        std::uint64_t version{};
        std::vector<std::uint32_t> indices;
    };

    std::uint32_t gaussianCount_{};
    std::uint32_t rangeCapacity_{};
    std::array<MetalPtr<MTL::Buffer>, gaussianSourceBufferCount_> gaussianSources_;
    std::vector<AetherGaussianGpu> canonicalGaussians_;
    std::array<std::uint64_t, gaussianSourceBufferCount_> sourceVersions_{};
    std::uint64_t currentVersion_{};
    std::vector<PublicationPatch> publicationJournal_;
    MetalPtr<MTL::Buffer> projected_;
    MetalPtr<MTL::Buffer> tileCounts_;
    MetalPtr<MTL::Buffer> offsets_;
    MetalPtr<MTL::Buffer> scanBlockSums_;
    MetalPtr<MTL::Buffer> radixHistograms_;
    MetalPtr<MTL::Buffer> radixGroupOffsets_;
    MetalPtr<MTL::Buffer> indirectDispatch_;
    MetalPtr<MTL::Buffer> keysA_;
    MetalPtr<MTL::Buffer> keysB_;
    MetalPtr<MTL::Buffer> valuesA_;
    MetalPtr<MTL::Buffer> valuesB_;
    MetalPtr<MTL::Buffer> ranges_;
    MetalPtr<MTL::Buffer> counters_;
    std::array<MetalPtr<MTL::ComputePipelineState>, 13> pipelines_;
    mutable std::mutex publicationMutex_;
    GaussianPublicationStatistics lastPublicationStatistics_{};
    GaussianPublicationStatistics lastFramePublicationStatistics_{};
};

} // namespace aether::metal
