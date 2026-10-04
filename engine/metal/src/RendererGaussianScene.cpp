#include <aether/metal/Renderer.hpp>

#include <algorithm>
#include <cstdint>

namespace aether::metal {
namespace {

[[nodiscard]] std::uint32_t gaussianTileEntryBudget(std::size_t gaussianCount) noexcept {
    constexpr std::uint64_t minimumEntries = 262'144;
    constexpr std::uint64_t maximumEntries = 4'194'304;
    constexpr std::uint64_t expectedTilesPerGaussian = 64;
    const std::uint64_t requested =
        gaussianCount > maximumEntries / expectedTilesPerGaussian
            ? maximumEntries
            : static_cast<std::uint64_t>(gaussianCount) * expectedTilesPerGaussian;
    return static_cast<std::uint32_t>(std::clamp(requested, minimumEntries, maximumEntries));
}

class FrameQuiescence final {
  public:
    FrameQuiescence(dispatch_semaphore_t semaphore, std::size_t slotCount) noexcept
        : semaphore_(semaphore) {
        for (; acquired_ < slotCount; ++acquired_)
            dispatch_semaphore_wait(semaphore_, DISPATCH_TIME_FOREVER);
    }

    ~FrameQuiescence() {
        for (std::size_t index = 0; index < acquired_; ++index)
            dispatch_semaphore_signal(semaphore_);
    }

    FrameQuiescence(const FrameQuiescence&) = delete;
    FrameQuiescence& operator=(const FrameQuiescence&) = delete;

  private:
    dispatch_semaphore_t semaphore_{};
    std::size_t acquired_{};
};

} // namespace

Result<void> Renderer::loadGaussianAsset(const gaussian::GaussianAsset& asset) {
    auto pipeline = GaussianPipeline::create(device_.get(), shaderLibrary_.get(),
                                             gaussianTileEntryBudget(asset.gaussians.size()));
    if (!pipeline)
        return std::unexpected(pipeline.error());
    if (auto loaded = (*pipeline)->load(asset); !loaded)
        return std::unexpected(loaded.error());

    // Build/upload first, then stop every frame only for the short publication window. This keeps
    // failed replacement non-mutating while preventing an in-flight command buffer from retaining
    // resources owned by the old pipeline after it is destroyed.
    FrameQuiescence quiescence(frameSemaphore_, frameContexts_.size());
    meshPrimitives_.clear();
    meshInstances_.clear();
    meshAnimationAsset_.reset();
    meshWorldTransforms_.clear();
    previousMeshWorldTransforms_.clear();
    selectedAnimation_.reset();
    meshTextures_.clear();
    meshMaterials_.clear();
    gaussianPipeline_ = std::move(*pipeline);
    proxyVertices_.reset();
    proxyIndices_.reset();
    proxyVertexCount_ = 0;
    proxyIndexCount_ = 0;
    selectedMeshEntity_ = 0;
    temporalHistoryValid_ = false;
    return {};
}

void Renderer::clearCapturedGaussianScene() noexcept {
    FrameQuiescence quiescence(frameSemaphore_, frameContexts_.size());
    gaussianPipeline_.reset();
    proxyVertices_.reset();
    proxyIndices_.reset();
    proxyVertexCount_ = 0;
    proxyIndexCount_ = 0;
    temporalHistoryValid_ = false;
}

} // namespace aether::metal
