#pragma once

#include <aether/core/Error.hpp>
#include <aether/scene/Camera.hpp>
#include <aether/scene/Lighting.hpp>

#include <simd/simd.h>

#include <array>
#include <cstdint>
#include <vector>

namespace aether::scene {

struct DirectionalShadowConfig final {
    std::uint32_t cascadeCount{4};
    std::uint32_t resolution{2048};
    float maximumDistance{200.0F};
    float splitLambda{0.7F};
    float depthPadding{50.0F};
};

struct DirectionalShadowCascades final {
    /// Positive camera-space far depth for each cascade.
    std::vector<float> splitDepths;
    std::vector<simd_float4x4> worldToShadowClip;
};

struct LocalShadowConfig final {
    std::uint32_t resolution{1024};
    float nearPlane{0.05F};
};

struct SpotShadowProjection final {
    simd_float4x4 worldToShadowClip{matrix_identity_float4x4};
    float nearPlane{};
    float farPlane{};
};

struct PointShadowProjection final {
    std::array<simd_float4x4, 6> worldToShadowClip{};
    float nearPlane{};
    float farPlane{};
};

struct LocalShadowAllocation final {
    std::uint32_t sourceLightIndex{};
    std::uint32_t baseSlice{};
    std::uint32_t sliceCount{};
};

/// Computes stable orthographic cascade matrices in Metal's [0,1] depth convention.
[[nodiscard]] Result<DirectionalShadowCascades> buildDirectionalShadowCascades(
    const Camera& camera, const Transform& cameraWorldTransform, float aspectRatio,
    simd_float3 lightDirection, const DirectionalShadowConfig& config = {});

[[nodiscard]] Result<SpotShadowProjection> buildSpotShadowProjection(
    const Light& light, const LocalShadowConfig& config = {});

/// Face order matches Metal cube textures: +X, -X, +Y, -Y, +Z, -Z.
[[nodiscard]] Result<PointShadowProjection> buildPointShadowProjection(
    const Light& light, const LocalShadowConfig& config = {});

/// Admits at most four spot and two point lights in stable source order into sixteen slices.
[[nodiscard]] Result<std::vector<LocalShadowAllocation>> selectLocalShadowLights(
    const std::vector<Light>& lights);

} // namespace aether::scene
