#pragma once

#include <aether/core/Error.hpp>
#include <aether/gaussian/GaussianAsset.hpp>
#include <aether/metal/MetalPtr.hpp>
#include <shared/AetherShaderTypes.h>

#include <Metal/Metal.hpp>

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>

namespace aether::metal {

struct GaussianPipelineStatistics final {
    std::uint32_t visibleGaussians{};
    std::uint32_t tileEntries{};
    std::uint32_t overflowedEntries{};
    std::uint32_t earlyTerminations{};
};

/// Keeps the current editor implementation from feeding multi-million-splat assets into every
/// projection/sort/composite pass. The complete asset remains resident; only the live viewport
/// workload is bounded. A proper spatial LOD hierarchy can replace this temporary stability gate.
struct ResponsiveGaussianCount final {
    static constexpr std::uint32_t viewportBudget = 180'000;
    std::uint32_t loaded{};

    ResponsiveGaussianCount& operator=(std::uint32_t value) noexcept {
        loaded = value;
        return *this;
    }

    [[nodiscard]] operator std::uint32_t() const noexcept {
        return std::min(loaded, viewportBudget);
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

    /// Input: command buffer, calibrated camera, and writable color/depth/ID textures.
    /// Output: ordered compute work on the caller's command buffer.
    /// Task: render front-to-back splats and expose bounded overflow through counters.
    [[nodiscard]] Result<void> encode(MTL::CommandBuffer* commandBuffer,
                                      AetherGaussianCamera camera, MTL::Texture* color,
                                      MTL::Texture* depth, MTL::Texture* ids);

    /// Call only after the encoded command buffer completes.
    [[nodiscard]] GaussianPipelineStatistics statistics() const noexcept;

  private:
    GaussianPipeline(MTL::Device* device, std::uint32_t maximumTileEntries);
    [[nodiscard]] Result<void> buildPipelines(MTL::Library* library);
    [[nodiscard]] Result<void> ensureTileRanges(std::uint32_t tileCount);
    [[nodiscard]] Result<void>
    dispatch1D(MTL::CommandBuffer* commandBuffer, MTL::ComputePipelineState* pipeline,
               std::uint32_t threads, const char* label,
               const std::function<void(MTL::ComputeCommandEncoder*)>& bind) const;

    MetalPtr<MTL::Device> device_;
    std::uint32_t maximumTileEntries_{};
    ResponsiveGaussianCount gaussianCount_{};
    std::uint32_t rangeCapacity_{};
    MetalPtr<MTL::Buffer> gaussians_;
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
};

} // namespace aether::metal
