#pragma once

#include <aether/core/Error.hpp>

#include <simd/simd.h>

#include <cstdint>
#include <vector>

namespace aether::scene {

struct EquirectangularEnvironment final {
    std::uint32_t width{};
    std::uint32_t height{};
    std::vector<simd_float3> linearRgb;
};

struct CubeMapLevel final {
    std::uint32_t size{};
    /// Face-major order: +X, -X, +Y, -Y, +Z, -Z; row-major within each face.
    std::vector<simd_float3> linearRgb;
};

struct IblPreprocessConfig final {
    std::uint32_t irradianceSize{32};
    std::uint32_t specularSize{128};
    std::uint32_t specularMipCount{8};
    std::uint32_t brdfLutSize{256};
    std::uint32_t diffuseSamples{256};
    std::uint32_t specularSamples{512};
    std::uint32_t brdfSamples{512};
    std::uint64_t maximumOutputTexels{16ULL * 1024ULL * 1024ULL};
};

struct ImageBasedLightingData final {
    CubeMapLevel irradiance;
    std::vector<CubeMapLevel> prefilteredSpecular;
    std::uint32_t brdfLutSize{};
    std::vector<simd_float2> brdfLut;
};

/// Produces deterministic diffuse/specular split-sum IBL data from linear HDR pixels.
[[nodiscard]] Result<ImageBasedLightingData> preprocessImageBasedLighting(
    const EquirectangularEnvironment& source, const IblPreprocessConfig& config = {});

/// Bilinear, horizontally wrapped sampling used by preprocessing and reference tests.
[[nodiscard]] Result<simd_float3> sampleEnvironment(const EquirectangularEnvironment& source,
                                                    simd_float3 direction);

} // namespace aether::scene
