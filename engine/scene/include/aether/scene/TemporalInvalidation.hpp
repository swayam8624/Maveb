#pragma once

#include <aether/core/Error.hpp>

#include <cstdint>
#include <simd/simd.h>

namespace aether::scene {

struct TemporalWorldBounds final {
    simd_float3 minimum{};
    simd_float3 maximum{};
};

[[nodiscard]] TemporalWorldBounds
mergeTemporalWorldBounds(const TemporalWorldBounds& first,
                         const TemporalWorldBounds& second) noexcept;

struct TemporalInvalidationPlan final {
    bool fullFrame{};
    bool empty{};
    simd_float4 normalizedRect{}; // minU, minV, maxU, maxV
    std::uint64_t invalidatedPixels{};
    std::uint64_t fullFramePixels{};

    [[nodiscard]] double pixelRatio() const noexcept {
        if (fullFramePixels == 0)
            return 0.0;
        return static_cast<double>(invalidatedPixels) /
               static_cast<double>(fullFramePixels);
    }
};

/// Projects a conservative world-space AABB into a top-left-origin normalized screen rectangle.
///
/// If any corner lies at/behind the camera plane, the projection is not guaranteed conservative
/// under simple corner projection, so the function deliberately falls back to full-frame
/// invalidation. Off-screen bounds produce an empty plan. expansionPixels covers raster/filter
/// footprint and numerical motion around the projected rectangle.
[[nodiscard]] Result<TemporalInvalidationPlan>
planTemporalInvalidation(const TemporalWorldBounds& bounds, simd_float4x4 viewProjection,
                         std::uint32_t width, std::uint32_t height,
                         std::uint32_t expansionPixels = 4);

} // namespace aether::scene
