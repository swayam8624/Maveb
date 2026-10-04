#pragma once

#include <algorithm>
#include <cstddef>
#include <span>
#include <vector>

#include <simd/simd.h>

namespace aether::mesh {

/// Input: candidate instance indices, parallel world-space centers, and camera position.
/// Output: a stable far-to-near order suitable for conventional source-over alpha blending.
/// Task: make transparent submission deterministic and independently testable from Metal.
/// Precondition: every candidate index addresses `worldCenters`.
inline std::vector<std::size_t> stableBackToFront(
    std::span<const std::size_t> candidates, std::span<const simd_float3> worldCenters,
    simd_float3 cameraPosition) {
    std::vector<std::size_t> result(candidates.begin(), candidates.end());
    std::stable_sort(result.begin(), result.end(), [&](std::size_t a, std::size_t b) {
        return simd_length_squared(worldCenters[a] - cameraPosition) >
               simd_length_squared(worldCenters[b] - cameraPosition);
    });
    return result;
}

} // namespace aether::mesh
