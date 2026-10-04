#include <aether/gaussian/GaussianCodec.hpp>

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <limits>

namespace aether::gaussian {
namespace {

constexpr std::array<std::byte, 8> magic{std::byte{'A'}, std::byte{'E'}, std::byte{'T'},
                                         std::byte{'H'}, std::byte{'G'}, std::byte{'S'},
                                         std::byte{0},   std::byte{0}};

void append16(std::vector<std::byte>& output, std::uint16_t value) {
    for (std::size_t byte = 0; byte < sizeof(value); ++byte)
        output.push_back(static_cast<std::byte>((value >> (byte * 8U)) & 0xffU));
}

void append32(std::vector<std::byte>& output, std::uint32_t value) {
    for (std::size_t byte = 0; byte < sizeof(value); ++byte)
        output.push_back(static_cast<std::byte>((value >> (byte * 8U)) & 0xffU));
}

void append64(std::vector<std::byte>& output, std::uint64_t value) {
    for (std::size_t byte = 0; byte < sizeof(value); ++byte)
        output.push_back(static_cast<std::byte>((value >> (byte * 8U)) & 0xffU));
}

void appendFloat(std::vector<std::byte>& output, float value) {
    append32(output, std::bit_cast<std::uint32_t>(value));
}

std::uint16_t read16(const std::byte* bytes) {
    std::uint16_t value{};
    for (std::size_t byte = 0; byte < sizeof(value); ++byte)
        value |= static_cast<std::uint16_t>(std::to_integer<std::uint8_t>(bytes[byte]))
                 << (byte * 8U);
    return value;
}

std::uint32_t read32(const std::byte* bytes) {
    std::uint32_t value{};
    for (std::size_t byte = 0; byte < sizeof(value); ++byte)
        value |= static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(bytes[byte]))
                 << (byte * 8U);
    return value;
}

std::uint64_t read64(const std::byte* bytes) {
    std::uint64_t value{};
    for (std::size_t byte = 0; byte < sizeof(value); ++byte)
        value |= static_cast<std::uint64_t>(std::to_integer<std::uint8_t>(bytes[byte]))
                 << (byte * 8U);
    return value;
}

float readFloat(const std::byte* bytes) {
    return std::bit_cast<float>(read32(bytes));
}

std::size_t expectedRestCount(std::size_t degree) {
    constexpr std::array counts{0U, 9U, 24U, 45U};
    return degree < counts.size() ? counts[degree] : std::numeric_limits<std::size_t>::max();
}

Result<void> validate(const Gaussian& gaussian, std::size_t restCount) {
    auto finite = [](float value) { return std::isfinite(value) && std::abs(value) <= 1.0e12F; };
    if (!std::ranges::all_of(gaussian.position, finite) ||
        !std::ranges::all_of(gaussian.logScale, finite) ||
        !std::ranges::all_of(gaussian.rotation, finite) || !finite(gaussian.opacityLogit) ||
        !std::ranges::all_of(gaussian.dc, finite) || !std::ranges::all_of(gaussian.rest, finite)) {
        return fail(ErrorCode::corruptData, "Canonical Gaussian contains a non-finite value");
    }
    if (std::ranges::any_of(gaussian.logScale,
                            [](float value) { return value < -30.0F || value > 30.0F; })) {
        return fail(ErrorCode::corruptData, "Canonical Gaussian log scale is outside safe range");
    }
    double normSquared = 0.0;
    for (const float value : gaussian.rotation)
        normSquared += static_cast<double>(value) * value;
    if (normSquared < 0.999 || normSquared > 1.001)
        return fail(ErrorCode::corruptData, "Canonical Gaussian quaternion is not normalized");
    if (gaussian.restCount != restCount)
        return fail(ErrorCode::corruptData, "Canonical Gaussian SH degree is inconsistent");
    return {};
}

} // namespace

Result<std::vector<std::byte>> GaussianCodec::encode(const GaussianAsset& asset) {
    if (asset.gaussians.empty() || asset.sphericalHarmonicDegree > 3)
        return fail(ErrorCode::invalidArgument,
                    "Canonical Gaussian asset is empty or has invalid SH");
    const std::size_t restCount = expectedRestCount(asset.sphericalHarmonicDegree);
    if (asset.gaussians.size() >
        (std::numeric_limits<std::size_t>::max() - headerBytes) / recordBytes) {
        return fail(ErrorCode::resourceExhausted, "Canonical Gaussian byte size overflows");
    }
    std::vector<std::byte> output;
    output.reserve(headerBytes + asset.gaussians.size() * recordBytes);
    output.insert(output.end(), magic.begin(), magic.end());
    append16(output, 1);
    append16(output, 0);
    append32(output, recordBytes);
    append64(output, asset.gaussians.size());
    append32(output, static_cast<std::uint32_t>(asset.sphericalHarmonicDegree));
    append32(output, 0);
    for (const Gaussian& gaussian : asset.gaussians) {
        if (auto result = validate(gaussian, restCount); !result)
            return std::unexpected(result.error());
        const std::size_t recordStart = output.size();
        for (const float value : gaussian.position)
            appendFloat(output, value);
        for (const float value : gaussian.logScale)
            appendFloat(output, value);
        for (const float value : gaussian.rotation)
            appendFloat(output, value);
        appendFloat(output, gaussian.opacityLogit);
        for (const float value : gaussian.dc)
            appendFloat(output, value);
        for (const float value : gaussian.rest)
            appendFloat(output, value);
        append32(output, static_cast<std::uint32_t>(gaussian.restCount));
        output.resize(recordStart + recordBytes, std::byte{0});
    }
    return output;
}

Result<GaussianAsset> GaussianCodec::decode(std::span<const std::byte> bytes,
                                            std::size_t maximumGaussians) {
    if (bytes.size() < headerBytes || !std::equal(magic.begin(), magic.end(), bytes.begin()))
        return fail(ErrorCode::corruptData, "Canonical Gaussian chunk magic is invalid");
    if (read16(bytes.data() + 8) != 1)
        return fail(ErrorCode::unsupported,
                    "Canonical Gaussian chunk major version is unsupported");
    const std::uint32_t stride = read32(bytes.data() + 12);
    const std::uint64_t rawCount = read64(bytes.data() + 16);
    const std::uint32_t degree = read32(bytes.data() + 24);
    if (stride != recordBytes || degree > 3 || rawCount == 0 || rawCount > maximumGaussians ||
        rawCount > (bytes.size() - headerBytes) / recordBytes ||
        headerBytes + rawCount * recordBytes != bytes.size()) {
        return fail(ErrorCode::corruptData, "Canonical Gaussian chunk dimensions are invalid");
    }
    GaussianAsset asset;
    asset.sphericalHarmonicDegree = degree;
    asset.gaussians.resize(static_cast<std::size_t>(rawCount));
    const std::size_t restCount = expectedRestCount(degree);
    for (std::size_t index = 0; index < asset.gaussians.size(); ++index) {
        const std::byte* cursor = bytes.data() + headerBytes + index * recordBytes;
        Gaussian& gaussian = asset.gaussians[index];
        for (float& value : gaussian.position) {
            value = readFloat(cursor);
            cursor += 4;
        }
        for (float& value : gaussian.logScale) {
            value = readFloat(cursor);
            cursor += 4;
        }
        for (float& value : gaussian.rotation) {
            value = readFloat(cursor);
            cursor += 4;
        }
        gaussian.opacityLogit = readFloat(cursor);
        cursor += 4;
        for (float& value : gaussian.dc) {
            value = readFloat(cursor);
            cursor += 4;
        }
        for (float& value : gaussian.rest) {
            value = readFloat(cursor);
            cursor += 4;
        }
        gaussian.restCount = read32(cursor);
        if (auto result = validate(gaussian, restCount); !result)
            return std::unexpected(result.error());
    }
    return asset;
}

} // namespace aether::gaussian
