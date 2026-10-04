#pragma once

#include <aether/core/Error.hpp>

#include <simd/simd.h>

#include <cstdint>
#include <vector>

namespace aether::scene {

enum class LightType : std::uint32_t { directional, point, spot };

struct Light final {
    LightType type{LightType::directional};
    simd_float3 position{};
    float range{10.0F};
    simd_float3 direction{0.0F, -1.0F, 0.0F};
    simd_float3 color{1.0F, 1.0F, 1.0F};
    float intensity{1.0F};
    float innerConeRadians{0.35F};
    float outerConeRadians{0.55F};
};

struct ClusterGridConfig final {
    std::uint32_t columns{16};
    std::uint32_t rows{9};
    std::uint32_t depthSlices{24};
    std::uint32_t maximumLightReferences{1'000'000};
    std::uint32_t maximumClusters{1'000'000};
    float nearDepth{0.05F};
    float farDepth{10'000.0F};
};

struct ClusterEntry final {
    std::uint32_t offset{};
    std::uint32_t count{};
};

struct ClusteredLightLists final {
    ClusterGridConfig config;
    std::vector<ClusterEntry> clusters;
    std::vector<std::uint32_t> lightIndices;
};

/// Builds deterministic conservative screen/depth light lists for a perspective camera.
/// Directional lights affect every cluster. Point/spot bounds use their finite range sphere.
[[nodiscard]] Result<ClusteredLightLists> buildClusteredLightLists(
    const std::vector<Light>& lights, simd_float4x4 worldToView, simd_float4x4 projection,
    const ClusterGridConfig& config = {});

[[nodiscard]] Result<void> validateLight(const Light& light);

} // namespace aether::scene
