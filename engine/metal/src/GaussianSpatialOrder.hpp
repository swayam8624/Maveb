#pragma once

#include <aether/gaussian/GaussianAsset.hpp>

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <limits>
#include <numeric>
#include <vector>

namespace aether::metal::detail {

/// Builds a deterministic, coarse spatially progressive permutation for large Gaussian assets.
///
/// The viewport budget is prefix-based. Feeding the first N source splats therefore produces a
/// biased preview whenever the trainer/package happens to store spatially related splats next to
/// each other. This ordering places splats into a fixed 32^3 grid and emits one splat from each
/// occupied cell in round-robin order before emitting the next item from any cell.
///
/// Each cell is also split into four opacity-logit tiers. The round-robin traversal always consumes
/// the strongest remaining tier in a cell first, so scarce preview slots are not spent on nearly
/// transparent splats while a stronger representative of the same region is still available.
/// Small assets are left in canonical order so correctness fixtures retain their historical IDs.
///
/// Complexity is O(N + G*T), where G = 32^3 and T = 4. There is no N log N sort on import.
[[nodiscard]] inline std::vector<std::uint32_t>
buildProgressiveSpatialOrder(const gaussian::GaussianAsset& asset) {
    const std::size_t count = asset.gaussians.size();
    std::vector<std::uint32_t> identity(count);
    std::iota(identity.begin(), identity.end(), 0U);

    constexpr std::size_t spatialOrderingThreshold = 250'000;
    constexpr std::uint32_t gridResolution = 32;
    constexpr std::uint32_t gridCellCount =
        gridResolution * gridResolution * gridResolution;
    constexpr std::uint32_t opacityTierCount = 4;
    constexpr std::uint32_t groupedBucketCount = gridCellCount * opacityTierCount;

    if (count <= spatialOrderingThreshold)
        return identity;

    std::array<float, 3> minimum{std::numeric_limits<float>::max(),
                                 std::numeric_limits<float>::max(),
                                 std::numeric_limits<float>::max()};
    std::array<float, 3> maximum{std::numeric_limits<float>::lowest(),
                                 std::numeric_limits<float>::lowest(),
                                 std::numeric_limits<float>::lowest()};
    for (const auto& gaussian : asset.gaussians) {
        for (std::size_t axis = 0; axis < 3; ++axis) {
            minimum[axis] = std::min(minimum[axis], gaussian.position[axis]);
            maximum[axis] = std::max(maximum[axis], gaussian.position[axis]);
        }
    }

    const auto quantize = [&](float value, std::size_t axis) -> std::uint32_t {
        const float extent = maximum[axis] - minimum[axis];
        if (!(extent > 1.0e-8F))
            return 0;
        const float normalized = std::clamp((value - minimum[axis]) / extent, 0.0F, 1.0F);
        return std::min(gridResolution - 1U,
                        static_cast<std::uint32_t>(normalized * gridResolution));
    };
    const auto cellFor = [&](const gaussian::Gaussian& gaussian) -> std::uint32_t {
        const std::uint32_t x = quantize(gaussian.position[0], 0);
        const std::uint32_t y = quantize(gaussian.position[1], 1);
        const std::uint32_t z = quantize(gaussian.position[2], 2);
        return (z * gridResolution + y) * gridResolution + x;
    };
    const auto opacityTierFor = [](const gaussian::Gaussian& gaussian) -> std::uint32_t {
        // Approximate sigmoid opacity bands without evaluating exp on the import path.
        // logit 1.5 ~= opacity 0.82, 0 ~= 0.5, -1.5 ~= 0.18.
        if (gaussian.opacityLogit >= 1.5F)
            return 3U;
        if (gaussian.opacityLogit >= 0.0F)
            return 2U;
        if (gaussian.opacityLogit >= -1.5F)
            return 1U;
        return 0U;
    };
    const auto bucketFor = [&](const gaussian::Gaussian& gaussian) -> std::uint32_t {
        return cellFor(gaussian) * opacityTierCount + opacityTierFor(gaussian);
    };

    std::vector<std::uint32_t> counts(groupedBucketCount, 0U);
    std::vector<std::uint32_t> cellCounts(gridCellCount, 0U);
    for (const auto& gaussian : asset.gaussians) {
        ++counts[bucketFor(gaussian)];
        ++cellCounts[cellFor(gaussian)];
    }

    std::vector<std::uint32_t> offsets(groupedBucketCount + 1U, 0U);
    for (std::uint32_t bucket = 0; bucket < groupedBucketCount; ++bucket)
        offsets[bucket + 1U] = offsets[bucket] + counts[bucket];

    std::vector<std::uint32_t> writeCursor(offsets.begin(), offsets.end() - 1);
    std::vector<std::uint32_t> grouped(count);
    for (std::uint32_t sourceIndex = 0; sourceIndex < count; ++sourceIndex) {
        const std::uint32_t bucket = bucketFor(asset.gaussians[sourceIndex]);
        grouped[writeCursor[bucket]++] = sourceIndex;
    }

    std::vector<std::uint32_t> readCursor(offsets.begin(), offsets.end() - 1);
    std::deque<std::uint32_t> activeCells;
    for (std::uint32_t cell = 0; cell < gridCellCount; ++cell)
        if (cellCounts[cell] != 0U)
            activeCells.push_back(cell);

    const auto strongestNonEmptyBucket = [&](std::uint32_t cell) -> std::uint32_t {
        for (std::uint32_t reverseTier = 0; reverseTier < opacityTierCount; ++reverseTier) {
            const std::uint32_t tier = opacityTierCount - 1U - reverseTier;
            const std::uint32_t bucket = cell * opacityTierCount + tier;
            if (readCursor[bucket] < offsets[bucket + 1U])
                return bucket;
        }
        return groupedBucketCount;
    };

    std::vector<std::uint32_t> progressive;
    progressive.reserve(count);
    while (!activeCells.empty()) {
        const std::uint32_t cell = activeCells.front();
        activeCells.pop_front();
        const std::uint32_t bucket = strongestNonEmptyBucket(cell);
        if (bucket == groupedBucketCount)
            continue;
        progressive.push_back(grouped[readCursor[bucket]++]);
        if (progressive.size() < count && strongestNonEmptyBucket(cell) != groupedBucketCount)
            activeCells.push_back(cell);
    }
    return progressive;
}

} // namespace aether::metal::detail
