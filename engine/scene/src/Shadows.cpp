#include <aether/scene/Shadows.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>

namespace aether::scene {
namespace {
simd_float4x4 lookAt(simd_float3 eye, simd_float3 forward) {
    forward = simd_normalize(forward);
    const simd_float3 referenceUp = std::abs(forward.y) < 0.99F ? simd_float3{0, 1, 0}
                                                                : simd_float3{1, 0, 0};
    const simd_float3 right = simd_normalize(simd_cross(forward, referenceUp));
    const simd_float3 up = simd_cross(right, forward);
    return simd_float4x4{
        simd_float4{right.x, up.x, -forward.x, 0},
        simd_float4{right.y, up.y, -forward.y, 0},
        simd_float4{right.z, up.z, -forward.z, 0},
        simd_float4{-simd_dot(right, eye), -simd_dot(up, eye), simd_dot(forward, eye), 1}};
}

simd_float4x4 lookAt(simd_float3 eye, simd_float3 forward, simd_float3 referenceUp) {
    forward = simd_normalize(forward);
    const simd_float3 right = simd_normalize(simd_cross(forward, referenceUp));
    const simd_float3 up = simd_cross(right, forward);
    return simd_float4x4{
        simd_float4{right.x, up.x, -forward.x, 0},
        simd_float4{right.y, up.y, -forward.y, 0},
        simd_float4{right.z, up.z, -forward.z, 0},
        simd_float4{-simd_dot(right, eye), -simd_dot(up, eye), simd_dot(forward, eye), 1}};
}

simd_float4x4 perspective(float verticalFieldOfView, float aspect, float nearDepth,
                          float farDepth) {
    const float y = 1.0F / std::tan(verticalFieldOfView * 0.5F);
    const float x = y / aspect;
    const float z = farDepth / (nearDepth - farDepth);
    const float translation = nearDepth * farDepth / (nearDepth - farDepth);
    return simd_float4x4{simd_float4{x, 0, 0, 0}, simd_float4{0, y, 0, 0},
                         simd_float4{0, 0, z, -1}, simd_float4{0, 0, translation, 0}};
}

simd_float4x4 orthographic(float left, float right, float bottom, float top, float nearDepth,
                           float farDepth) {
    return simd_float4x4{
        simd_float4{2.0F / (right - left), 0, 0, 0},
        simd_float4{0, 2.0F / (top - bottom), 0, 0},
        simd_float4{0, 0, 1.0F / (nearDepth - farDepth), 0},
        simd_float4{-(right + left) / (right - left), -(top + bottom) / (top - bottom),
                    nearDepth / (nearDepth - farDepth), 1}};
}

bool finiteMatrix(const simd_float4x4& matrix) {
    for (const auto column : matrix.columns)
        for (std::size_t row = 0; row < 4; ++row)
            if (!std::isfinite(column[row])) return false;
    return true;
}
} // namespace

Result<DirectionalShadowCascades> buildDirectionalShadowCascades(
    const Camera& camera, const Transform& cameraWorldTransform, float aspectRatio,
    simd_float3 lightDirection, const DirectionalShadowConfig& config) {
    if (camera.projection != ProjectionType::perspective || !isFinite(cameraWorldTransform) ||
        !hasNonZeroScale(cameraWorldTransform) || !std::isfinite(aspectRatio) ||
        aspectRatio <= 0.0F || !std::isfinite(camera.verticalFieldOfViewRadians) ||
        camera.verticalFieldOfViewRadians <= 0.0F ||
        camera.verticalFieldOfViewRadians >= 3.14159265359F || camera.nearPlane <= 0.0F ||
        !std::isfinite(lightDirection.x) ||
        !std::isfinite(lightDirection.y) || !std::isfinite(lightDirection.z) ||
        simd_length_squared(lightDirection) < 1.0e-12F)
        return fail(ErrorCode::invalidArgument, "Directional shadow camera or light is invalid");
    if (config.cascadeCount == 0 || config.cascadeCount > 8 || config.resolution == 0 ||
        config.maximumDistance <= camera.nearPlane || config.splitLambda < 0.0F ||
        config.splitLambda > 1.0F || config.depthPadding <= 0.0F)
        return fail(ErrorCode::invalidArgument, "Directional shadow configuration is invalid");
    const float farDepth = std::min(config.maximumDistance,
                                    camera.infiniteFarPlane ? config.maximumDistance
                                                            : camera.farPlane);
    if (!std::isfinite(farDepth) || farDepth <= camera.nearPlane)
        return fail(ErrorCode::invalidArgument, "Directional shadow distance is invalid");

    DirectionalShadowCascades result;
    result.splitDepths.reserve(config.cascadeCount);
    result.worldToShadowClip.reserve(config.cascadeCount);
    const float nearDepth = camera.nearPlane;
    for (std::uint32_t cascade = 1; cascade <= config.cascadeCount; ++cascade) {
        const float fraction = static_cast<float>(cascade) /
                               static_cast<float>(config.cascadeCount);
        const float logarithmic = nearDepth * std::pow(farDepth / nearDepth, fraction);
        const float uniform = nearDepth + (farDepth - nearDepth) * fraction;
        result.splitDepths.push_back(
            config.splitLambda * logarithmic + (1.0F - config.splitLambda) * uniform);
    }

    const auto cameraToWorld = cameraWorldTransform.matrix();
    const float tangent = std::tan(camera.verticalFieldOfViewRadians * 0.5F);
    float cascadeNear = nearDepth;
    lightDirection = simd_normalize(lightDirection);
    for (const float cascadeFar : result.splitDepths) {
        std::array<simd_float3, 8> corners{};
        std::size_t corner = 0;
        for (const float depth : {cascadeNear, cascadeFar}) {
            const float halfHeight = tangent * depth;
            const float halfWidth = halfHeight * aspectRatio;
            for (const float y : {-halfHeight, halfHeight})
                for (const float x : {-halfWidth, halfWidth}) {
                    const auto world = simd_mul(cameraToWorld, simd_float4{x, y, -depth, 1});
                    corners[corner++] = {world.x, world.y, world.z};
                }
        }
        simd_float3 center{};
        for (const auto point : corners) center += point;
        center /= static_cast<float>(corners.size());
        float radius = 0.0F;
        for (const auto point : corners) radius = std::max(radius, simd_length(point - center));
        radius = std::ceil(radius * 16.0F) / 16.0F;
        const auto lightView = lookAt(center - lightDirection * (radius + config.depthPadding),
                                      lightDirection);
        const float largest = std::numeric_limits<float>::max();
        simd_float3 minimum{largest, largest, largest};
        simd_float3 maximum{-largest, -largest, -largest};
        for (const auto point : corners) {
            const auto lightSpace = simd_mul(lightView, simd_float4{point.x, point.y, point.z, 1});
            minimum = simd_min(minimum, lightSpace.xyz);
            maximum = simd_max(maximum, lightSpace.xyz);
        }
        const float extent = std::max(maximum.x - minimum.x, maximum.y - minimum.y);
        if (!std::isfinite(extent) || extent <= 1.0e-6F)
            return fail(ErrorCode::internal, "Directional shadow cascade extent is degenerate");
        const float texel = extent / static_cast<float>(config.resolution);
        float centerX = (minimum.x + maximum.x) * 0.5F;
        float centerY = (minimum.y + maximum.y) * 0.5F;
        centerX = std::floor(centerX / texel + 0.5F) * texel;
        centerY = std::floor(centerY / texel + 0.5F) * texel;
        const float halfExtent = extent * 0.5F;
        const float lightNear = std::max(0.001F, -maximum.z - config.depthPadding);
        const float lightFar = std::max(lightNear + 0.001F, -minimum.z + config.depthPadding);
        const auto matrix = simd_mul(
            orthographic(centerX - halfExtent, centerX + halfExtent,
                         centerY - halfExtent, centerY + halfExtent, lightNear, lightFar),
            lightView);
        if (!finiteMatrix(matrix))
            return fail(ErrorCode::internal, "Directional shadow cascade matrix is not finite");
        result.worldToShadowClip.push_back(matrix);
        cascadeNear = cascadeFar;
    }
    return result;
}

Result<SpotShadowProjection> buildSpotShadowProjection(const Light& light,
                                                        const LocalShadowConfig& config) {
    if (light.type != LightType::spot)
        return fail(ErrorCode::invalidArgument, "Spot shadow projection requires a spot light");
    if (auto valid = validateLight(light); !valid) return std::unexpected(valid.error());
    if (config.resolution == 0 || !std::isfinite(config.nearPlane) || config.nearPlane <= 0.0F ||
        config.nearPlane >= light.range)
        return fail(ErrorCode::invalidArgument, "Spot shadow configuration is invalid");
    const auto view = lookAt(light.position, light.direction);
    const auto projection = perspective(light.outerConeRadians * 2.0F, 1.0F,
                                        config.nearPlane, light.range);
    const auto matrix = simd_mul(projection, view);
    if (!finiteMatrix(matrix))
        return fail(ErrorCode::internal, "Spot shadow matrix is not finite");
    return SpotShadowProjection{matrix, config.nearPlane, light.range};
}

Result<PointShadowProjection> buildPointShadowProjection(const Light& light,
                                                          const LocalShadowConfig& config) {
    if (light.type != LightType::point)
        return fail(ErrorCode::invalidArgument, "Point shadow projection requires a point light");
    if (auto valid = validateLight(light); !valid) return std::unexpected(valid.error());
    if (config.resolution == 0 || !std::isfinite(config.nearPlane) || config.nearPlane <= 0.0F ||
        config.nearPlane >= light.range)
        return fail(ErrorCode::invalidArgument, "Point shadow configuration is invalid");
    constexpr std::array directions{
        simd_float3{1, 0, 0}, simd_float3{-1, 0, 0}, simd_float3{0, 1, 0},
        simd_float3{0, -1, 0}, simd_float3{0, 0, 1}, simd_float3{0, 0, -1}};
    constexpr std::array upVectors{
        simd_float3{0, -1, 0}, simd_float3{0, -1, 0}, simd_float3{0, 0, 1},
        simd_float3{0, 0, -1}, simd_float3{0, -1, 0}, simd_float3{0, -1, 0}};
    const auto projection = perspective(1.57079632679F, 1.0F, config.nearPlane, light.range);
    PointShadowProjection result;
    result.nearPlane = config.nearPlane;
    result.farPlane = light.range;
    for (std::size_t face = 0; face < result.worldToShadowClip.size(); ++face) {
        result.worldToShadowClip[face] =
            simd_mul(projection, lookAt(light.position, directions[face], upVectors[face]));
        if (!finiteMatrix(result.worldToShadowClip[face]))
            return fail(ErrorCode::internal, "Point shadow matrix is not finite");
    }
    return result;
}

Result<std::vector<LocalShadowAllocation>> selectLocalShadowLights(
    const std::vector<Light>& lights) {
    std::vector<LocalShadowAllocation> result;
    result.reserve(6);
    std::uint32_t spots = 0;
    std::uint32_t points = 0;
    std::uint32_t nextSlice = 0;
    for (std::size_t index = 0; index < lights.size(); ++index) {
        if (auto valid = validateLight(lights[index]); !valid)
            return std::unexpected(valid.error());
        std::uint32_t slices = 0;
        if (lights[index].type == LightType::spot && spots < 4) {
            slices = 1;
            ++spots;
        } else if (lights[index].type == LightType::point && points < 2) {
            slices = 6;
            ++points;
        }
        if (slices == 0) continue;
        result.push_back({static_cast<std::uint32_t>(index), nextSlice, slices});
        nextSlice += slices;
    }
    return result;
}

} // namespace aether::scene
