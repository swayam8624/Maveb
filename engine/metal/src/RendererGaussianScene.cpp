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

} // namespace

Result<void> Renderer::loadGaussianAsset(const gaussian::GaussianAsset& asset) {
    auto pipeline = GaussianPipeline::create(device_.get(), shaderLibrary_.get(),
                                             gaussianTileEntryBudget(asset.gaussians.size()));
    if (!pipeline)
        return std::unexpected(pipeline.error());
    if (auto loaded = (*pipeline)->load(asset); !loaded)
        return std::unexpected(loaded.error());

    // Publish only after the replacement Gaussian pipeline is fully allocated and uploaded.
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

} // namespace aether::metal
