#include <aether/gaussian/PlyLoader.hpp>

#include <algorithm>
#include <array>
#include <bit>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <limits>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

namespace aether::gaussian {
namespace {

enum class Format { ascii, binaryLittleEndian };
enum class ScalarType { int8, uint8, int16, uint16, int32, uint32, float32, float64 };

struct Property final {
    ScalarType type;
    std::string name;
};

struct Header final {
    Format format{};
    std::size_t vertexCount{};
    std::vector<Property> properties;
    std::streamoff payloadOffset{};
};

std::optional<ScalarType> scalarType(std::string_view name) {
    if (name == "char" || name == "int8")
        return ScalarType::int8;
    if (name == "uchar" || name == "uint8")
        return ScalarType::uint8;
    if (name == "short" || name == "int16")
        return ScalarType::int16;
    if (name == "ushort" || name == "uint16")
        return ScalarType::uint16;
    if (name == "int" || name == "int32")
        return ScalarType::int32;
    if (name == "uint" || name == "uint32")
        return ScalarType::uint32;
    if (name == "float" || name == "float32")
        return ScalarType::float32;
    if (name == "double" || name == "float64")
        return ScalarType::float64;
    return std::nullopt;
}

std::size_t scalarBytes(ScalarType type) {
    switch (type) {
    case ScalarType::int8:
    case ScalarType::uint8:
        return 1;
    case ScalarType::int16:
    case ScalarType::uint16:
        return 2;
    case ScalarType::int32:
    case ScalarType::uint32:
    case ScalarType::float32:
        return 4;
    case ScalarType::float64:
        return 8;
    }
    return 0;
}

Result<std::size_t> parseCount(std::string_view text) {
    std::uint64_t value{};
    const auto result = std::from_chars(text.data(), text.data() + text.size(), value);
    if (result.ec != std::errc{} || result.ptr != text.data() + text.size() ||
        value > std::numeric_limits<std::size_t>::max()) {
        return fail(ErrorCode::corruptData, "PLY element count is invalid", std::string(text));
    }
    return static_cast<std::size_t>(value);
}

Result<Header> readHeader(std::ifstream& stream, const PlyLimits& limits) {
    Header header;
    std::string line;
    if (!std::getline(stream, line) || (line != "ply" && line != "ply\r")) {
        return fail(ErrorCode::corruptData, "PLY magic is missing");
    }
    bool hasFormat = false;
    bool hasVertex = false;
    bool insideVertex = false;
    std::size_t headerBytes = line.size() + 1;
    while (std::getline(stream, line)) {
        headerBytes += line.size() + 1;
        if (headerBytes > limits.maximumHeaderBytes)
            return fail(ErrorCode::resourceExhausted, "PLY header exceeds its byte limit");
        if (!line.empty() && line.back() == '\r')
            line.pop_back();
        std::istringstream tokens(line);
        std::string command;
        tokens >> command;
        if (command.empty() || command == "comment" || command == "obj_info")
            continue;
        if (command == "format") {
            std::string format;
            std::string version;
            tokens >> format >> version;
            if (hasFormat || version != "1.0")
                return fail(ErrorCode::corruptData, "PLY format declaration is invalid");
            if (format == "ascii")
                header.format = Format::ascii;
            else if (format == "binary_little_endian")
                header.format = Format::binaryLittleEndian;
            else
                return fail(ErrorCode::unsupported,
                            "Only ASCII and binary-little-endian PLY are supported", format);
            hasFormat = true;
        } else if (command == "element") {
            std::string name;
            std::string countText;
            tokens >> name >> countText;
            auto count = parseCount(countText);
            if (!count)
                return std::unexpected(count.error());
            insideVertex = name == "vertex";
            if (insideVertex) {
                if (hasVertex)
                    return fail(ErrorCode::corruptData, "PLY declares vertex more than once");
                header.vertexCount = *count;
                hasVertex = true;
            } else if (*count != 0) {
                return fail(ErrorCode::unsupported,
                            "3DGS PLY cannot contain populated non-vertex elements", name);
            }
        } else if (command == "property") {
            if (!insideVertex)
                continue;
            std::string typeName;
            std::string propertyName;
            tokens >> typeName >> propertyName;
            if (typeName == "list")
                return fail(ErrorCode::unsupported, "PLY vertex list properties are unsupported");
            auto type = scalarType(typeName);
            if (!type || propertyName.empty())
                return fail(ErrorCode::unsupported, "PLY vertex scalar type is unsupported",
                            typeName);
            if (header.properties.size() >= limits.maximumProperties)
                return fail(ErrorCode::resourceExhausted, "PLY exceeds its property limit");
            if (std::ranges::any_of(header.properties, [&](const Property& property) {
                    return property.name == propertyName;
                })) {
                return fail(ErrorCode::corruptData, "PLY property name is duplicated",
                            propertyName);
            }
            header.properties.push_back(Property{*type, std::move(propertyName)});
        } else if (command == "end_header") {
            header.payloadOffset = stream.tellg();
            if (header.payloadOffset < 0)
                return fail(ErrorCode::io, "Unable to locate PLY payload");
            if (!hasFormat || !hasVertex || header.vertexCount == 0 || header.properties.empty())
                return fail(ErrorCode::corruptData, "PLY header is incomplete");
            if (header.vertexCount > limits.maximumGaussians)
                return fail(ErrorCode::resourceExhausted, "PLY exceeds its Gaussian limit");
            return header;
        } else {
            return fail(ErrorCode::corruptData, "Unknown PLY header directive", command);
        }
    }
    return fail(ErrorCode::corruptData, "PLY header is truncated");
}

template <typename UInt> Result<UInt> readUnsigned(std::ifstream& stream) {
    std::array<unsigned char, sizeof(UInt)> bytes{};
    stream.read(reinterpret_cast<char*>(bytes.data()), bytes.size());
    if (!stream)
        return fail(ErrorCode::corruptData, "PLY binary payload is truncated");
    UInt value{};
    for (std::size_t index = 0; index < bytes.size(); ++index)
        value |= static_cast<UInt>(bytes[index]) << (index * 8U);
    return value;
}

Result<double> readBinaryScalar(std::ifstream& stream, ScalarType type) {
    switch (type) {
    case ScalarType::int8: {
        auto value = readUnsigned<std::uint8_t>(stream);
        if (!value)
            return std::unexpected(value.error());
        return static_cast<std::int8_t>(*value);
    }
    case ScalarType::uint8: {
        auto value = readUnsigned<std::uint8_t>(stream);
        if (!value)
            return std::unexpected(value.error());
        return *value;
    }
    case ScalarType::int16: {
        auto value = readUnsigned<std::uint16_t>(stream);
        if (!value)
            return std::unexpected(value.error());
        return static_cast<std::int16_t>(*value);
    }
    case ScalarType::uint16: {
        auto value = readUnsigned<std::uint16_t>(stream);
        if (!value)
            return std::unexpected(value.error());
        return *value;
    }
    case ScalarType::int32: {
        auto value = readUnsigned<std::uint32_t>(stream);
        if (!value)
            return std::unexpected(value.error());
        return static_cast<std::int32_t>(*value);
    }
    case ScalarType::uint32: {
        auto value = readUnsigned<std::uint32_t>(stream);
        if (!value)
            return std::unexpected(value.error());
        return *value;
    }
    case ScalarType::float32: {
        auto bits = readUnsigned<std::uint32_t>(stream);
        if (!bits)
            return std::unexpected(bits.error());
        return std::bit_cast<float>(*bits);
    }
    case ScalarType::float64: {
        auto bits = readUnsigned<std::uint64_t>(stream);
        if (!bits)
            return std::unexpected(bits.error());
        return std::bit_cast<double>(*bits);
    }
    }
    return fail(ErrorCode::internal, "Unreachable PLY scalar type");
}

std::optional<std::size_t> indexedProperty(std::string_view name, std::string_view prefix) {
    if (!name.starts_with(prefix))
        return std::nullopt;
    const std::string_view suffix = name.substr(prefix.size());
    std::size_t value{};
    const auto result = std::from_chars(suffix.data(), suffix.data() + suffix.size(), value);
    if (suffix.empty() || result.ec != std::errc{} || result.ptr != suffix.data() + suffix.size())
        return std::nullopt;
    return value;
}

Result<void> assign(Gaussian& gaussian, const Property& property, double value) {
    if (!std::isfinite(value) || std::abs(value) > 1.0e12)
        return fail(ErrorCode::corruptData, "PLY Gaussian property is non-finite or unreasonable",
                    property.name);
    const float scalar = static_cast<float>(value);
    const auto scaleIndex = indexedProperty(property.name, "scale_");
    const auto rotationIndex = indexedProperty(property.name, "rot_");
    const auto dcIndex = indexedProperty(property.name, "f_dc_");
    const auto restIndex = indexedProperty(property.name, "f_rest_");
    if (property.name == "x")
        gaussian.position[0] = scalar;
    else if (property.name == "y")
        gaussian.position[1] = scalar;
    else if (property.name == "z")
        gaussian.position[2] = scalar;
    else if (property.name == "opacity")
        gaussian.opacityLogit = scalar;
    else if (scaleIndex && *scaleIndex < 3)
        gaussian.logScale[*scaleIndex] = scalar;
    else if (rotationIndex && *rotationIndex < 4)
        gaussian.rotation[*rotationIndex] = scalar;
    else if (dcIndex && *dcIndex < 3)
        gaussian.dc[*dcIndex] = scalar;
    else if (restIndex && *restIndex < 45)
        gaussian.rest[*restIndex] = scalar;
    return {};
}

Result<std::size_t> validateSchema(const Header& header, GaussianAsset& asset) {
    constexpr std::array required{"x",      "y",       "z",       "f_dc_0",  "f_dc_1",
                                  "f_dc_2", "opacity", "scale_0", "scale_1", "scale_2",
                                  "rot_0",  "rot_1",   "rot_2",   "rot_3"};
    for (std::string_view name : required) {
        if (std::ranges::none_of(header.properties,
                                 [&](const Property& property) { return property.name == name; })) {
            return fail(ErrorCode::corruptData, "PLY is missing a required 3DGS property",
                        std::string(name));
        }
    }
    std::size_t restCount = 0;
    for (const Property& property : header.properties) {
        if (auto index = indexedProperty(property.name, "f_rest_")) {
            if (*index >= 45)
                return fail(ErrorCode::unsupported, "PLY spherical harmonics exceed degree 3");
            restCount = std::max(restCount, *index + 1);
        } else if (std::ranges::none_of(
                       required, [&](std::string_view name) { return property.name == name; })) {
            asset.diagnostics.push_back("Ignored unregistered vertex property: " + property.name);
        }
    }
    for (std::size_t index = 0; index < restCount; ++index) {
        const std::string expected = "f_rest_" + std::to_string(index);
        if (std::ranges::none_of(header.properties, [&](const Property& property) {
                return property.name == expected;
            })) {
            return fail(ErrorCode::corruptData, "PLY spherical-harmonic properties are not dense",
                        expected);
        }
    }
    if (restCount != 0 && restCount != 9 && restCount != 24 && restCount != 45)
        return fail(ErrorCode::corruptData,
                    "PLY spherical-harmonic property count is not degree 0, 1, 2, or 3");
    return restCount;
}

Result<void> normalize(Gaussian& gaussian, std::size_t restCount,
                       float maximumAbsoluteLogScale) {
    double normSquared = 0.0;
    for (const float value : gaussian.rotation)
        normSquared += static_cast<double>(value) * value;
    if (normSquared < 1.0e-16)
        return fail(ErrorCode::corruptData, "PLY Gaussian contains a zero quaternion");
    const float inverseNorm = static_cast<float>(1.0 / std::sqrt(normSquared));
    for (float& value : gaussian.rotation)
        value *= inverseNorm;
    for (const float value : gaussian.logScale) {
        if (std::abs(value) > maximumAbsoluteLogScale)
            return fail(ErrorCode::corruptData, "PLY Gaussian log scale is outside safe range");
    }
    gaussian.restCount = restCount;
    return {};
}

} // namespace

Result<GaussianAsset> PlyLoader::load(const std::filesystem::path& path, const PlyLimits& limits) {
    if (!std::isfinite(limits.maximumAbsoluteLogScale) ||
        limits.maximumAbsoluteLogScale <= 0.0F) {
        return fail(ErrorCode::invalidArgument,
                    "PLY maximum absolute log scale must be finite and positive");
    }
    std::error_code filesystemError;
    const auto fileBytes = std::filesystem::file_size(path, filesystemError);
    if (filesystemError)
        return fail(ErrorCode::notFound, "Unable to read PLY file", path.string());
    if (fileBytes == 0 || fileBytes > limits.maximumFileBytes)
        return fail(ErrorCode::resourceExhausted, "PLY file size is empty or exceeds its limit",
                    path.string());
    std::ifstream stream(path, std::ios::binary);
    auto header = readHeader(stream, limits);
    if (!header)
        return std::unexpected(header.error());

    GaussianAsset asset;
    asset.name = path.stem().string();
    auto restCount = validateSchema(*header, asset);
    if (!restCount)
        return std::unexpected(restCount.error());
    asset.sphericalHarmonicDegree =
        *restCount == 45 ? 3 : (*restCount == 24 ? 2 : (*restCount == 9 ? 1 : 0));
    asset.gaussians.resize(header->vertexCount);

    if (header->format == Format::binaryLittleEndian) {
        std::size_t stride = 0;
        for (const Property& property : header->properties) {
            if (stride > std::numeric_limits<std::size_t>::max() - scalarBytes(property.type))
                return fail(ErrorCode::resourceExhausted, "PLY binary stride overflows");
            stride += scalarBytes(property.type);
        }
        if (header->vertexCount >
                (fileBytes - static_cast<std::uintmax_t>(header->payloadOffset)) / stride ||
            header->vertexCount * stride !=
                fileBytes - static_cast<std::uintmax_t>(header->payloadOffset)) {
            return fail(ErrorCode::corruptData,
                        "PLY binary payload size does not match its header");
        }
        for (Gaussian& gaussian : asset.gaussians) {
            for (const Property& property : header->properties) {
                auto value = readBinaryScalar(stream, property.type);
                if (!value)
                    return std::unexpected(value.error());
                if (auto result = assign(gaussian, property, *value); !result)
                    return std::unexpected(result.error());
            }
            if (auto result = normalize(gaussian, *restCount, limits.maximumAbsoluteLogScale);
                !result)
                return std::unexpected(result.error());
        }
    } else {
        std::string line;
        for (Gaussian& gaussian : asset.gaussians) {
            if (!std::getline(stream, line))
                return fail(ErrorCode::corruptData, "PLY ASCII payload is truncated");
            std::istringstream values(line);
            for (const Property& property : header->properties) {
                double value{};
                if (!(values >> value))
                    return fail(ErrorCode::corruptData, "PLY ASCII vertex has too few values");
                if (auto result = assign(gaussian, property, value); !result)
                    return std::unexpected(result.error());
            }
            std::string extra;
            if (values >> extra)
                return fail(ErrorCode::corruptData, "PLY ASCII vertex has too many values");
            if (auto result = normalize(gaussian, *restCount, limits.maximumAbsoluteLogScale);
                !result)
                return std::unexpected(result.error());
        }
        while (std::getline(stream, line)) {
            if (line.find_first_not_of(" \t\r") != std::string::npos)
                return fail(ErrorCode::corruptData, "PLY ASCII payload has trailing data");
        }
    }
    return asset;
}

} // namespace aether::gaussian
