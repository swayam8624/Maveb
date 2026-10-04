#include <aether/scene/ImageBasedLighting.hpp>

#include <algorithm>
#include <cmath>
#include <limits>

namespace aether::scene {
namespace {
constexpr float pi = 3.14159265358979323846F;

float radicalInverse(std::uint32_t bits) {
    bits = (bits << 16U) | (bits >> 16U);
    bits = ((bits & 0x55555555U) << 1U) | ((bits & 0xAAAAAAAAU) >> 1U);
    bits = ((bits & 0x33333333U) << 2U) | ((bits & 0xCCCCCCCCU) >> 2U);
    bits = ((bits & 0x0F0F0F0FU) << 4U) | ((bits & 0xF0F0F0F0U) >> 4U);
    bits = ((bits & 0x00FF00FFU) << 8U) | ((bits & 0xFF00FF00U) >> 8U);
    return static_cast<float>(bits) * 2.3283064365386963e-10F;
}

simd_float2 hammersley(std::uint32_t index, std::uint32_t count) {
    return {static_cast<float>(index) / static_cast<float>(count), radicalInverse(index)};
}

simd_float3 cubeDirection(std::uint32_t face, std::uint32_t x, std::uint32_t y,
                          std::uint32_t size) {
    const float u = (2.0F * (static_cast<float>(x) + 0.5F) / static_cast<float>(size)) - 1.0F;
    const float v = (2.0F * (static_cast<float>(y) + 0.5F) / static_cast<float>(size)) - 1.0F;
    const simd_float3 directions[6]{{1, -v, -u}, {-1, -v, u}, {u, 1, v},
                                    {u, -1, -v}, {u, -v, 1}, {-u, -v, -1}};
    return simd_normalize(directions[face]);
}

void basis(simd_float3 normal, simd_float3& tangent, simd_float3& bitangent) {
    const simd_float3 up = std::abs(normal.z) < 0.999F ? simd_float3{0, 0, 1}
                                                       : simd_float3{1, 0, 0};
    tangent = simd_normalize(simd_cross(up, normal));
    bitangent = simd_cross(normal, tangent);
}

simd_float3 localToWorld(simd_float3 local, simd_float3 normal) {
    simd_float3 tangent;
    simd_float3 bitangent;
    basis(normal, tangent, bitangent);
    return simd_normalize(tangent * local.x + bitangent * local.y + normal * local.z);
}

simd_float3 cosineHemisphere(simd_float2 sample) {
    const float radius = std::sqrt(sample.x);
    const float phi = 2.0F * pi * sample.y;
    return {radius * std::cos(phi), radius * std::sin(phi), std::sqrt(1.0F - sample.x)};
}

simd_float3 importanceSampleGgx(simd_float2 sample, float roughness, simd_float3 normal) {
    const float alpha = roughness * roughness;
    const float phi = 2.0F * pi * sample.x;
    const float cosine = std::sqrt((1.0F - sample.y) /
                                   (1.0F + (alpha * alpha - 1.0F) * sample.y));
    const float sine = std::sqrt(std::max(0.0F, 1.0F - cosine * cosine));
    return localToWorld(simd_float3{sine * std::cos(phi), sine * std::sin(phi), cosine}, normal);
}

float geometrySchlick(float nDotV, float roughness) {
    const float k = (roughness * roughness) * 0.5F;
    return nDotV / (nDotV * (1.0F - k) + k);
}

Result<void> validate(const EquirectangularEnvironment& source, const IblPreprocessConfig& config) {
    const std::uint64_t sourceTexels = static_cast<std::uint64_t>(source.width) * source.height;
    if (source.width < 2 || source.height < 2 || sourceTexels != source.linearRgb.size())
        return fail(ErrorCode::invalidArgument, "HDR environment dimensions do not match pixels");
    if (config.irradianceSize == 0 || config.specularSize == 0 || config.specularMipCount == 0 ||
        config.brdfLutSize == 0 || config.diffuseSamples == 0 || config.specularSamples == 0 ||
        config.brdfSamples == 0)
        return fail(ErrorCode::invalidArgument, "IBL preprocessing dimensions and samples must be non-zero");
    std::uint64_t output = static_cast<std::uint64_t>(config.irradianceSize) *
                           config.irradianceSize * 6;
    std::uint32_t mipSize = config.specularSize;
    for (std::uint32_t mip = 0; mip < config.specularMipCount; ++mip) {
        output += static_cast<std::uint64_t>(mipSize) * mipSize * 6;
        mipSize = std::max(1U, mipSize / 2U);
    }
    output += static_cast<std::uint64_t>(config.brdfLutSize) * config.brdfLutSize;
    if (output > config.maximumOutputTexels)
        return fail(ErrorCode::resourceExhausted, "IBL preprocessing exceeds output texel budget");
    for (const auto pixel : source.linearRgb)
        if (!std::isfinite(pixel.x) || !std::isfinite(pixel.y) || !std::isfinite(pixel.z) ||
            simd_reduce_min(pixel) < 0.0F)
            return fail(ErrorCode::invalidArgument, "HDR environment pixels must be finite and non-negative");
    return {};
}
} // namespace

Result<simd_float3> sampleEnvironment(const EquirectangularEnvironment& source,
                                      simd_float3 direction) {
    if (source.width < 2 || source.height < 2 ||
        static_cast<std::uint64_t>(source.width) * source.height != source.linearRgb.size() ||
        !std::isfinite(direction.x) || !std::isfinite(direction.y) ||
        !std::isfinite(direction.z) || simd_length_squared(direction) < 1.0e-12F)
        return fail(ErrorCode::invalidArgument, "Cannot sample invalid HDR environment or direction");
    direction = simd_normalize(direction);
    float u = std::atan2(direction.z, direction.x) / (2.0F * pi) + 0.5F;
    u -= std::floor(u);
    const float v = std::acos(std::clamp(direction.y, -1.0F, 1.0F)) / pi;
    const float x = u * static_cast<float>(source.width) - 0.5F;
    const float y = v * static_cast<float>(source.height) - 0.5F;
    const auto x0Signed = static_cast<std::int64_t>(std::floor(x));
    const auto y0Signed = static_cast<std::int64_t>(std::floor(y));
    const auto wrapX = [&](std::int64_t value) {
        const auto width = static_cast<std::int64_t>(source.width);
        return static_cast<std::uint32_t>((value % width + width) % width);
    };
    const auto clampY = [&](std::int64_t value) {
        return static_cast<std::uint32_t>(std::clamp<std::int64_t>(
            value, 0, static_cast<std::int64_t>(source.height) - 1));
    };
    const float fx = x - std::floor(x);
    const float fy = y - std::floor(y);
    const auto pixel = [&](std::int64_t px, std::int64_t py) {
        return source.linearRgb[static_cast<std::size_t>(clampY(py)) * source.width + wrapX(px)];
    };
    return simd_mix(simd_mix(pixel(x0Signed, y0Signed), pixel(x0Signed + 1, y0Signed), fx),
                    simd_mix(pixel(x0Signed, y0Signed + 1), pixel(x0Signed + 1, y0Signed + 1), fx),
                    fy);
}

Result<ImageBasedLightingData> preprocessImageBasedLighting(
    const EquirectangularEnvironment& source, const IblPreprocessConfig& config) {
    if (auto valid = validate(source, config); !valid) return std::unexpected(valid.error());
    ImageBasedLightingData result;
    result.irradiance.size = config.irradianceSize;
    result.irradiance.linearRgb.resize(static_cast<std::size_t>(config.irradianceSize) *
                                       config.irradianceSize * 6);
    for (std::uint32_t face = 0; face < 6; ++face)
        for (std::uint32_t y = 0; y < config.irradianceSize; ++y)
            for (std::uint32_t x = 0; x < config.irradianceSize; ++x) {
                const auto normal = cubeDirection(face, x, y, config.irradianceSize);
                simd_float3 sum{};
                for (std::uint32_t sample = 0; sample < config.diffuseSamples; ++sample)
                    sum += *sampleEnvironment(source, localToWorld(
                        cosineHemisphere(hammersley(sample, config.diffuseSamples)), normal));
                result.irradiance.linearRgb[(static_cast<std::size_t>(face) * config.irradianceSize + y) *
                                                config.irradianceSize + x] =
                    sum * (pi / static_cast<float>(config.diffuseSamples));
            }
    std::uint32_t mipSize = config.specularSize;
    result.prefilteredSpecular.reserve(config.specularMipCount);
    for (std::uint32_t mip = 0; mip < config.specularMipCount; ++mip) {
        CubeMapLevel level;
        level.size = mipSize;
        level.linearRgb.resize(static_cast<std::size_t>(mipSize) * mipSize * 6);
        const float roughness = config.specularMipCount == 1
                                    ? 0.0F
                                    : static_cast<float>(mip) /
                                          static_cast<float>(config.specularMipCount - 1);
        for (std::uint32_t face = 0; face < 6; ++face)
            for (std::uint32_t y = 0; y < mipSize; ++y)
                for (std::uint32_t x = 0; x < mipSize; ++x) {
                    const auto normal = cubeDirection(face, x, y, mipSize);
                    simd_float3 sum{};
                    float weight = 0.0F;
                    for (std::uint32_t sample = 0; sample < config.specularSamples; ++sample) {
                        const auto halfVector = importanceSampleGgx(
                            hammersley(sample, config.specularSamples), std::max(roughness, 0.001F), normal);
                        const auto light = simd_normalize(2.0F * simd_dot(normal, halfVector) * halfVector - normal);
                        const float nDotL = std::max(simd_dot(normal, light), 0.0F);
                        if (nDotL > 0.0F) {
                            sum += *sampleEnvironment(source, light) * nDotL;
                            weight += nDotL;
                        }
                    }
                    level.linearRgb[(static_cast<std::size_t>(face) * mipSize + y) * mipSize + x] =
                        weight > 0.0F ? sum / weight : simd_float3{};
                }
        result.prefilteredSpecular.push_back(std::move(level));
        mipSize = std::max(1U, mipSize / 2U);
    }
    result.brdfLutSize = config.brdfLutSize;
    result.brdfLut.resize(static_cast<std::size_t>(config.brdfLutSize) * config.brdfLutSize);
    for (std::uint32_t y = 0; y < config.brdfLutSize; ++y)
        for (std::uint32_t x = 0; x < config.brdfLutSize; ++x) {
            const float nDotV = (static_cast<float>(x) + 0.5F) /
                                static_cast<float>(config.brdfLutSize);
            const float roughness = (static_cast<float>(y) + 0.5F) /
                                    static_cast<float>(config.brdfLutSize);
            const simd_float3 view{std::sqrt(1.0F - nDotV * nDotV), 0, nDotV};
            float scale = 0.0F;
            float bias = 0.0F;
            for (std::uint32_t sample = 0; sample < config.brdfSamples; ++sample) {
                const auto halfVector = importanceSampleGgx(hammersley(sample, config.brdfSamples),
                                                            roughness, simd_float3{0, 0, 1});
                const auto light = simd_normalize(2.0F * simd_dot(view, halfVector) * halfVector - view);
                const float nDotL = std::max(light.z, 0.0F);
                const float nDotH = std::max(halfVector.z, 0.0F);
                const float vDotH = std::max(simd_dot(view, halfVector), 0.0F);
                if (nDotL > 0.0F) {
                    const float geometry = geometrySchlick(nDotV, roughness) *
                                           geometrySchlick(nDotL, roughness);
                    const float visibility = geometry * vDotH / std::max(nDotH * nDotV, 1.0e-6F);
                    const float fresnel = std::pow(1.0F - vDotH, 5.0F);
                    scale += (1.0F - fresnel) * visibility;
                    bias += fresnel * visibility;
                }
            }
            result.brdfLut[static_cast<std::size_t>(y) * config.brdfLutSize + x] =
                {scale / config.brdfSamples, bias / config.brdfSamples};
        }
    return result;
}

} // namespace aether::scene
