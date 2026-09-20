#include <aether/scene/TemporalInvalidation.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>

namespace aether::scene {
namespace {

[[nodiscard]] bool finite3(simd_float3 value) noexcept {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}

[[nodiscard]] bool finiteMatrix(simd_float4x4 matrix) noexcept {
    for (std::size_t column = 0; column < 4; ++column)
        for (std::size_t row = 0; row < 4; ++row)
            if (!std::isfinite(matrix.columns[column][row]))
                return false;
    return true;
}

} // namespace

Result<TemporalInvalidationPlan>
planTemporalInvalidation(const TemporalWorldBounds& bounds, simd_float4x4 viewProjection,
                         std::uint32_t width, std::uint32_t height,
                         std::uint32_t expansionPixels) {
    if (width == 0 || height == 0)
        return fail(ErrorCode::invalidArgument, "Temporal invalidation viewport is empty");
    if (!finite3(bounds.minimum) || !finite3(bounds.maximum) ||
        simd_any(bounds.minimum > bounds.maximum) || !finiteMatrix(viewProjection)) {
        return fail(ErrorCode::invalidArgument, "Temporal invalidation inputs are invalid");
    }

    const std::uint64_t fullPixels =
        static_cast<std::uint64_t>(width) * static_cast<std::uint64_t>(height);
    std::array<simd_float3, 8> corners{};
    std::size_t index{};
    for (int z = 0; z < 2; ++z)
        for (int y = 0; y < 2; ++y)
            for (int x = 0; x < 2; ++x)
                corners[index++] = {
                    x == 0 ? bounds.minimum.x : bounds.maximum.x,
                    y == 0 ? bounds.minimum.y : bounds.maximum.y,
                    z == 0 ? bounds.minimum.z : bounds.maximum.z,
                };

    float minimumU = std::numeric_limits<float>::infinity();
    float minimumV = std::numeric_limits<float>::infinity();
    float maximumU = -std::numeric_limits<float>::infinity();
    float maximumV = -std::numeric_limits<float>::infinity();

    for (const simd_float3 corner : corners) {
        const simd_float4 clip = simd_mul(
            viewProjection, simd_float4{corner.x, corner.y, corner.z, 1.0F});
        if (!std::isfinite(clip.x) || !std::isfinite(clip.y) ||
            !std::isfinite(clip.w) || clip.w <= 1.0e-5F) {
            return TemporalInvalidationPlan{
                .fullFrame = true,
                .empty = false,
                .normalizedRect = {0.0F, 0.0F, 1.0F, 1.0F},
                .invalidatedPixels = fullPixels,
                .fullFramePixels = fullPixels,
            };
        }
        const float ndcX = clip.x / clip.w;
        const float ndcY = clip.y / clip.w;
        const float u = ndcX * 0.5F + 0.5F;
        const float v = 0.5F - ndcY * 0.5F;
        minimumU = std::min(minimumU, u);
        minimumV = std::min(minimumV, v);
        maximumU = std::max(maximumU, u);
        maximumV = std::max(maximumV, v);
    }

    if (maximumU < 0.0F || maximumV < 0.0F || minimumU > 1.0F || minimumV > 1.0F) {
        return TemporalInvalidationPlan{
            .fullFrame = false,
            .empty = true,
            .normalizedRect = {},
            .invalidatedPixels = 0,
            .fullFramePixels = fullPixels,
        };
    }

    const float expandU = static_cast<float>(expansionPixels) / static_cast<float>(width);
    const float expandV = static_cast<float>(expansionPixels) / static_cast<float>(height);
    minimumU = std::clamp(minimumU - expandU, 0.0F, 1.0F);
    minimumV = std::clamp(minimumV - expandV, 0.0F, 1.0F);
    maximumU = std::clamp(maximumU + expandU, 0.0F, 1.0F);
    maximumV = std::clamp(maximumV + expandV, 0.0F, 1.0F);

    const auto firstX = static_cast<std::uint64_t>(
        std::floor(minimumU * static_cast<float>(width)));
    const auto firstY = static_cast<std::uint64_t>(
        std::floor(minimumV * static_cast<float>(height)));
    const auto lastX = static_cast<std::uint64_t>(
        std::ceil(maximumU * static_cast<float>(width)));
    const auto lastY = static_cast<std::uint64_t>(
        std::ceil(maximumV * static_cast<float>(height)));
    const std::uint64_t invalidated =
        std::min<std::uint64_t>(lastX, width) - std::min<std::uint64_t>(firstX, width);
    const std::uint64_t invalidatedRows =
        std::min<std::uint64_t>(lastY, height) - std::min<std::uint64_t>(firstY, height);

    return TemporalInvalidationPlan{
        .fullFrame = false,
        .empty = invalidated == 0 || invalidatedRows == 0,
        .normalizedRect = {minimumU, minimumV, maximumU, maximumV},
        .invalidatedPixels = invalidated * invalidatedRows,
        .fullFramePixels = fullPixels,
    };
}

} // namespace aether::scene
