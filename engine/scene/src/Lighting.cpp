#include <aether/scene/Lighting.hpp>

#include <algorithm>
#include <cmath>
#include <limits>

namespace aether::scene {
namespace {
bool finite(simd_float3 value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}

std::uint32_t depthSlice(float depth, const ClusterGridConfig& config) {
    const float normalized = std::log(depth / config.nearDepth) /
                             std::log(config.farDepth / config.nearDepth);
    return std::min(config.depthSlices - 1,
                    static_cast<std::uint32_t>(std::max(0.0F, normalized) *
                                               static_cast<float>(config.depthSlices)));
}

std::uint32_t screenCell(float normalized, std::uint32_t count) {
    const float scaled = std::clamp(normalized, 0.0F, 0.999999F) * static_cast<float>(count);
    return std::min(count - 1, static_cast<std::uint32_t>(scaled));
}
} // namespace

Result<void> validateLight(const Light& light) {
    if (!finite(light.position) || !finite(light.direction) || !finite(light.color) ||
        !std::isfinite(light.range) || !std::isfinite(light.intensity) ||
        !std::isfinite(light.innerConeRadians) || !std::isfinite(light.outerConeRadians))
        return fail(ErrorCode::invalidArgument, "Light contains non-finite values");
    if (light.intensity < 0.0F || simd_reduce_min(light.color) < 0.0F)
        return fail(ErrorCode::invalidArgument, "Light intensity and color must be non-negative");
    if (light.type != LightType::directional && light.range <= 0.0F)
        return fail(ErrorCode::invalidArgument, "Local light range must be positive");
    if (light.type != LightType::point && simd_length_squared(light.direction) < 1.0e-12F)
        return fail(ErrorCode::invalidArgument, "Light direction must be non-zero");
    if (light.type == LightType::spot &&
        (light.innerConeRadians < 0.0F || light.outerConeRadians <= light.innerConeRadians ||
         light.outerConeRadians >= 1.57079632679F))
        return fail(ErrorCode::invalidArgument, "Spot cone angles are invalid");
    return {};
}

Result<ClusteredLightLists> buildClusteredLightLists(const std::vector<Light>& lights,
                                                      simd_float4x4 worldToView,
                                                      simd_float4x4 projection,
                                                      const ClusterGridConfig& config) {
    if (config.columns == 0 || config.rows == 0 || config.depthSlices == 0 ||
        config.nearDepth <= 0.0F || config.farDepth <= config.nearDepth)
        return fail(ErrorCode::invalidArgument, "Cluster grid configuration is invalid");
    const std::uint64_t clusterCount64 = static_cast<std::uint64_t>(config.columns) * config.rows *
                                         config.depthSlices;
    if (clusterCount64 > config.maximumClusters ||
        clusterCount64 > std::numeric_limits<std::uint32_t>::max())
        return fail(ErrorCode::resourceExhausted, "Cluster grid is too large");
    for (const auto& light : lights)
        if (auto valid = validateLight(light); !valid) return std::unexpected(valid.error());

    const auto clusterCount = static_cast<std::size_t>(clusterCount64);
    std::vector<std::vector<std::uint32_t>> temporary(clusterCount);
    std::size_t totalReferences = 0;
    auto append = [&](std::uint32_t lightIndex, std::uint32_t minX, std::uint32_t maxX,
                      std::uint32_t minY, std::uint32_t maxY, std::uint32_t minZ,
                      std::uint32_t maxZ) -> Result<void> {
        for (std::uint32_t z = minZ; z <= maxZ; ++z)
            for (std::uint32_t y = minY; y <= maxY; ++y)
                for (std::uint32_t x = minX; x <= maxX; ++x) {
                    if (totalReferences >= config.maximumLightReferences)
                        return fail(ErrorCode::resourceExhausted,
                                    "Clustered light references exceed configured budget");
                    const auto cluster = (static_cast<std::size_t>(z) * config.rows + y) *
                                             config.columns +
                                         x;
                    temporary[cluster].push_back(lightIndex);
                    ++totalReferences;
                }
        return {};
    };

    for (std::size_t index = 0; index < lights.size(); ++index) {
        if (index > std::numeric_limits<std::uint32_t>::max())
            return fail(ErrorCode::resourceExhausted, "Light index exceeds GPU representation");
        const auto& light = lights[index];
        if (light.type == LightType::directional) {
            if (auto added = append(static_cast<std::uint32_t>(index), 0, config.columns - 1, 0,
                                    config.rows - 1, 0, config.depthSlices - 1);
                !added)
                return std::unexpected(added.error());
            continue;
        }
        const simd_float4 viewPosition = simd_mul(
            worldToView, simd_float4{light.position.x, light.position.y, light.position.z, 1.0F});
        const float depth = -viewPosition.z;
        const float rawMinimumDepth = depth - light.range;
        const float rawMaximumDepth = depth + light.range;
        if (rawMaximumDepth < config.nearDepth || rawMinimumDepth > config.farDepth ||
            depth <= 0.0F)
            continue;
        const float minimumDepth = std::max(config.nearDepth, rawMinimumDepth);
        const float maximumDepth = std::min(config.farDepth, rawMaximumDepth);
        const simd_float4 clip = simd_mul(projection, viewPosition);
        if (std::abs(clip.w) < 1.0e-8F) continue;
        const simd_float2 centerNdc{clip.x / clip.w, clip.y / clip.w};
        const float boundDepth = std::max(config.nearDepth, depth - light.range);
        const simd_float2 radiusNdc{
            std::abs(projection.columns[0].x) * light.range / boundDepth,
            std::abs(projection.columns[1].y) * light.range / boundDepth};
        if (centerNdc.x + radiusNdc.x < -1.0F || centerNdc.x - radiusNdc.x > 1.0F ||
            centerNdc.y + radiusNdc.y < -1.0F || centerNdc.y - radiusNdc.y > 1.0F)
            continue;
        const std::uint32_t minX = screenCell((centerNdc.x - radiusNdc.x) * 0.5F + 0.5F,
                                               config.columns);
        const std::uint32_t maxX = screenCell((centerNdc.x + radiusNdc.x) * 0.5F + 0.5F,
                                               config.columns);
        const std::uint32_t minY = screenCell((1.0F - (centerNdc.y + radiusNdc.y)) * 0.5F,
                                               config.rows);
        const std::uint32_t maxY = screenCell((1.0F - (centerNdc.y - radiusNdc.y)) * 0.5F,
                                               config.rows);
        if (auto added = append(static_cast<std::uint32_t>(index), std::min(minX, maxX),
                                std::max(minX, maxX), std::min(minY, maxY), std::max(minY, maxY),
                                depthSlice(minimumDepth, config), depthSlice(maximumDepth, config));
            !added)
            return std::unexpected(added.error());
    }

    ClusteredLightLists result;
    result.config = config;
    result.clusters.resize(clusterCount);
    for (std::size_t cluster = 0; cluster < temporary.size(); ++cluster) {
        result.clusters[cluster] = {
            static_cast<std::uint32_t>(result.lightIndices.size()),
            static_cast<std::uint32_t>(temporary[cluster].size())};
        result.lightIndices.insert(result.lightIndices.end(), temporary[cluster].begin(),
                                   temporary[cluster].end());
    }
    return result;
}

} // namespace aether::scene
