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
/// each other. This ordering places splats into a fixed 32^3 grid and then emits one splat from
/// each occupied cell in round-robin order before emitting the second item from any cell. Small
/// assets are left in canonical order so correctness fixtures retain their exact historical IDs.
///
/// Complexity is O(N + G), where G = 32^3. There is no N log N sort on the import path.
[[nodiscard]] inline std::vector<std::uint32_t>
buildProgressiveSpatialOrder(const gaussian::GaussianAsset& asset) {
    const std::size_t count = asset.gaussians.size();
    std::vector<std::uint32_t> identity(count);
    std::iota(identity.begin(), identity.end(), 0U);

    constexpr std::size_t spatialOrderingThreshold = 250'000;
    constexpr std::uint32_t gridResolution = 32;
    constexpr std::uint32_t gridCellCount =
        gridResolution * gridResolution * gridResolution;

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

    std::vector<std::uint32_t> counts(gridCellCount, 0U);
    for (const auto& gaussian : asset.gaussians)
        ++counts[cellFor(gaussian)];

    std::vector<std::uint32_t> offsets(gridCellCount + 1U, 0U);
    for (std::uint32_t cell = 0; cell < gridCellCount; ++cell)
        offsets[cell + 1U] = offsets[cell] + counts[cell];

    std::vector<std::uint32_t> writeCursor(offsets.begin(), offsets.end() - 1);
    std::vector<std::uint32_t> grouped(count);
    for (std::uint32_t sourceIndex = 0; sourceIndex < count; ++sourceIndex) {
        const std::uint32_t cell = cellFor(asset.gaussians[sourceIndex]);
        grouped[writeCursor[cell]++] = sourceIndex;
    }

    std::vector<std::uint32_t> readCursor(offsets.begin(), offsets.end() - 1);
    std::deque<std::uint32_t> activeCells;
    for (std::uint32_t cell = 0; cell < gridCellCount; ++cell)
        if (counts[cell] != 0U)
            activeCells.push_back(cell);

    std::vector<std::uint32_t> progressive;
    progressive.reserve(count);
    while (!activeCells.empty()) {
        const std::uint32_t cell = activeCells.front();
        activeCells.pop_front();
        progressive.push_back(grouped[readCursor[cell]++]);
        if (readCursor[cell] < offsets[cell + 1U])
            activeCells.push_back(cell);
    }
    return progressive;
}

} // namespace aether::metal::detail
