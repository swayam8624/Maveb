#include "GaussianSpatialOrder.hpp"

#include <aether/gaussian/GaussianAsset.hpp>

#include <algorithm>
#include <cstdint>
#include <iostream>
#include <numeric>
#include <vector>

namespace {

bool require(bool condition, const char* message) {
    if (!condition)
        std::cerr << "GaussianSpatialOrderTests: " << message << '\n';
    return condition;
}

aether::gaussian::Gaussian makeGaussian(float x, float y, float z, float opacityLogit = 0.0F) {
    aether::gaussian::Gaussian gaussian;
    gaussian.position = {x, y, z};
    gaussian.opacityLogit = opacityLogit;
    return gaussian;
}

bool smallAssetsRemainCanonical() {
    aether::gaussian::GaussianAsset asset;
    asset.gaussians = {makeGaussian(10.0F, 0.0F, 0.0F, -10.0F),
                       makeGaussian(-10.0F, 0.0F, 0.0F, 10.0F),
                       makeGaussian(0.0F, 10.0F, 0.0F)};
    const auto order = aether::metal::detail::buildProgressiveSpatialOrder(asset);
    return require(order == std::vector<std::uint32_t>({0U, 1U, 2U}),
                   "small correctness assets must preserve canonical ordering");
}

bool largeOrderingIsDeterministicPermutationAndPrefersStrongSplats() {
    constexpr std::uint32_t count = 250'001;
    constexpr std::uint32_t strongSource = 123'456;
    aether::gaussian::GaussianAsset asset;
    asset.gaussians.reserve(count);
    for (std::uint32_t index = 0; index < count; ++index) {
        // One occupied cell makes the opacity-tier property explicit: the first preview item must
        // be the strongest source even though it occurs deep in canonical source order.
        const float opacity = index == strongSource ? 5.0F : -5.0F;
        asset.gaussians.push_back(makeGaussian(1.0F, 2.0F, 3.0F, opacity));
    }

    const auto first = aether::metal::detail::buildProgressiveSpatialOrder(asset);
    const auto second = aether::metal::detail::buildProgressiveSpatialOrder(asset);
    if (!require(first == second, "ordering must be deterministic"))
        return false;
    if (!require(first.size() == count, "ordering must contain every Gaussian"))
        return false;
    if (!require(first.front() == strongSource,
                 "strongest splat in a spatial cell must lead that cell's preview order"))
        return false;

    std::vector<std::uint32_t> sorted = first;
    std::sort(sorted.begin(), sorted.end());
    for (std::uint32_t index = 0; index < count; ++index)
        if (!require(sorted[index] == index, "ordering must be a complete permutation"))
            return false;
    return true;
}

bool lowBudgetPrefixCoversSeparatedRegions() {
    constexpr std::uint32_t perRegion = 125'001;
    aether::gaussian::GaussianAsset asset;
    asset.gaussians.reserve(perRegion * 2U);

    // Intentionally pathological source ordering: every left-cluster splat is stored before every
    // right-cluster splat. A naive prefix budget would render only the left side.
    for (std::uint32_t index = 0; index < perRegion; ++index)
        asset.gaussians.push_back(makeGaussian(-50.0F, float(index % 17U) * 0.01F, 0.0F));
    for (std::uint32_t index = 0; index < perRegion; ++index)
        asset.gaussians.push_back(makeGaussian(50.0F, float(index % 17U) * 0.01F, 0.0F));

    const auto order = aether::metal::detail::buildProgressiveSpatialOrder(asset);
    if (!require(order.size() == asset.gaussians.size(), "two-region ordering size mismatch"))
        return false;

    constexpr std::size_t previewPrefix = 64;
    bool sawLeft = false;
    bool sawRight = false;
    for (std::size_t logicalIndex = 0;
         logicalIndex < std::min(previewPrefix, order.size()); ++logicalIndex) {
        const float x = asset.gaussians[order[logicalIndex]].position[0];
        sawLeft |= x < 0.0F;
        sawRight |= x > 0.0F;
    }
    return require(sawLeft && sawRight,
                   "low-budget prefix must cover spatially separated source regions");
}

} // namespace

int main() {
    const bool passed = smallAssetsRemainCanonical() &&
                        largeOrderingIsDeterministicPermutationAndPrefersStrongSplats() &&
                        lowBudgetPrefixCoversSeparatedRegions();
    if (!passed)
        return 1;
    std::cout << "GaussianSpatialOrderTests: PASS\n";
    return 0;
}
