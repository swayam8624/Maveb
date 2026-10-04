#include <aether/hybrid/ProxyPlyLoader.hpp>

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <limits>
#include <optional>
#include <sstream>
#include <string>
#include <vector>

namespace aether::hybrid {
namespace {
enum class Format { ascii, binaryLittleEndian };
enum class ScalarType { int8, uint8, int16, uint16, int32, uint32, float32, float64 };
enum class Element { none, vertex, face };

struct Property final {
    ScalarType type;
    std::string name;
};
struct Header final {
    Format format{};
    std::size_t vertexCount{};
    std::size_t faceCount{};
    std::vector<Property> vertexProperties;
    ScalarType faceCountType{ScalarType::uint8};
    ScalarType faceIndexType{ScalarType::uint32};
    bool hasFaceList{};
};

std::optional<ScalarType> parseType(std::string_view name) {
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

bool isInteger(ScalarType type) {
    return type != ScalarType::float32 && type != ScalarType::float64;
}

Result<Header> readHeader(std::ifstream& stream, const ProxyPlyLimits& limits) {
    Header header;
    std::string line;
    std::size_t headerBytes = 0;
    bool sawPly = false, sawFormat = false, ended = false;
    Element element = Element::none;
    while (std::getline(stream, line)) {
        headerBytes += line.size() + 1U;
        if (headerBytes > limits.maximumHeaderBytes)
            return fail(ErrorCode::resourceExhausted, "Proxy PLY header exceeds safety limit");
        std::istringstream tokens(line);
        std::string keyword;
        tokens >> keyword;
        if (!sawPly) {
            if (keyword != "ply")
                return fail(ErrorCode::corruptData, "Proxy file is not PLY");
            sawPly = true;
        } else if (keyword == "format") {
            std::string format, version, extra;
            if (!(tokens >> format >> version) || tokens >> extra || version != "1.0" || sawFormat)
                return fail(ErrorCode::corruptData, "Proxy PLY format declaration is invalid");
            if (format == "ascii")
                header.format = Format::ascii;
            else if (format == "binary_little_endian")
                header.format = Format::binaryLittleEndian;
            else
                return fail(ErrorCode::unsupported, "Proxy PLY format is unsupported");
            sawFormat = true;
        } else if (keyword == "comment" || keyword == "obj_info" || keyword.empty()) {
            continue;
        } else if (keyword == "element") {
            std::string name, extra;
            std::uint64_t count{};
            if (!(tokens >> name >> count) || tokens >> extra)
                return fail(ErrorCode::corruptData, "Proxy PLY element declaration is invalid");
            if (name == "vertex" && header.vertexCount == 0 && element == Element::none) {
                if (count < 3 || count > limits.maximumVertices)
                    return fail(ErrorCode::resourceExhausted, "Proxy PLY vertex count is invalid");
                header.vertexCount = static_cast<std::size_t>(count);
                element = Element::vertex;
            } else if (name == "face" && header.faceCount == 0 && element == Element::vertex) {
                if (count == 0 || count > limits.maximumTriangles)
                    return fail(ErrorCode::resourceExhausted, "Proxy PLY face count is invalid");
                header.faceCount = static_cast<std::size_t>(count);
                element = Element::face;
            } else {
                return fail(ErrorCode::unsupported, "Proxy PLY contains unsupported elements");
            }
        } else if (keyword == "property") {
            if (element == Element::vertex) {
                std::string typeName, name, extra;
                if (!(tokens >> typeName >> name) || tokens >> extra || typeName == "list")
                    return fail(ErrorCode::corruptData, "Proxy vertex property is invalid");
                auto type = parseType(typeName);
                if (!type || header.vertexProperties.size() >= limits.maximumVertexProperties)
                    return fail(ErrorCode::unsupported,
                                "Proxy vertex property type/count is unsupported");
                if (std::ranges::any_of(header.vertexProperties,
                                        [&](const Property& value) { return value.name == name; }))
                    return fail(ErrorCode::corruptData,
                                "Proxy PLY has duplicate vertex properties");
                header.vertexProperties.push_back({*type, std::move(name)});
            } else if (element == Element::face) {
                std::string list, countTypeName, indexTypeName, name, extra;
                if (!(tokens >> list >> countTypeName >> indexTypeName >> name) ||
                    tokens >> extra || list != "list" || name != "vertex_indices" ||
                    header.hasFaceList)
                    return fail(ErrorCode::unsupported, "Proxy face property is unsupported");
                auto countType = parseType(countTypeName);
                auto indexType = parseType(indexTypeName);
                if (!countType || !indexType || !isInteger(*countType) || !isInteger(*indexType))
                    return fail(ErrorCode::unsupported, "Proxy face scalar type is unsupported");
                header.faceCountType = *countType;
                header.faceIndexType = *indexType;
                header.hasFaceList = true;
            } else {
                return fail(ErrorCode::corruptData, "Proxy property appears before an element");
            }
        } else if (keyword == "end_header") {
            std::string extra;
            if (tokens >> extra)
                return fail(ErrorCode::corruptData, "Proxy PLY end_header is invalid");
            ended = true;
            break;
        } else {
            return fail(ErrorCode::unsupported, "Proxy PLY header directive is unsupported");
        }
    }
    if (!ended || !sawFormat || header.vertexCount < 3 || header.faceCount == 0 ||
        !header.hasFaceList)
        return fail(ErrorCode::corruptData, "Proxy PLY header is incomplete");
    constexpr std::array required{"x", "y", "z", "nx", "ny", "nz"};
    for (const auto name : required)
        if (std::ranges::none_of(header.vertexProperties,
                                 [&](const Property& value) { return value.name == name; }))
            return fail(ErrorCode::corruptData, "Proxy PLY is missing position or normal fields");
    return header;
}

template <typename T> Result<T> readBinary(std::ifstream& stream) {
    std::array<std::byte, sizeof(T)> bytes{};
    stream.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    if (!stream)
        return fail(ErrorCode::corruptData, "Proxy PLY binary payload is truncated");
    if constexpr (sizeof(T) == 1) {
        return std::bit_cast<T>(bytes);
    } else {
        using Bits =
            std::conditional_t<sizeof(T) == 2, std::uint16_t,
                               std::conditional_t<sizeof(T) == 4, std::uint32_t, std::uint64_t>>;
        Bits bits{};
        for (std::size_t index = 0; index < bytes.size(); ++index)
            bits |= static_cast<Bits>(std::to_integer<std::uint8_t>(bytes[index])) << (index * 8U);
        return std::bit_cast<T>(bits);
    }
}

Result<double> readBinaryScalar(std::ifstream& stream, ScalarType type) {
    switch (type) {
    case ScalarType::int8: {
        auto v = readBinary<std::int8_t>(stream);
        if (v)
            return *v;
        else
            return std::unexpected(v.error());
    }
    case ScalarType::uint8: {
        auto v = readBinary<std::uint8_t>(stream);
        if (v)
            return *v;
        else
            return std::unexpected(v.error());
    }
    case ScalarType::int16: {
        auto v = readBinary<std::int16_t>(stream);
        if (v)
            return *v;
        else
            return std::unexpected(v.error());
    }
    case ScalarType::uint16: {
        auto v = readBinary<std::uint16_t>(stream);
        if (v)
            return *v;
        else
            return std::unexpected(v.error());
    }
    case ScalarType::int32: {
        auto v = readBinary<std::int32_t>(stream);
        if (v)
            return *v;
        else
            return std::unexpected(v.error());
    }
    case ScalarType::uint32: {
        auto v = readBinary<std::uint32_t>(stream);
        if (v)
            return *v;
        else
            return std::unexpected(v.error());
    }
    case ScalarType::float32: {
        auto v = readBinary<float>(stream);
        if (v)
            return *v;
        else
            return std::unexpected(v.error());
    }
    case ScalarType::float64:
        return readBinary<double>(stream);
    }
}

Result<std::uint32_t> scalarIndex(double value, std::size_t vertexCount) {
    if (!std::isfinite(value) || value < 0.0 || value >= static_cast<double>(vertexCount) ||
        std::floor(value) != value || value > std::numeric_limits<std::uint32_t>::max())
        return fail(ErrorCode::corruptData, "Proxy PLY face index is invalid");
    return static_cast<std::uint32_t>(value);
}

Result<ProxyVertex> makeVertex(const Header& header, const std::vector<double>& values) {
    auto value = [&](std::string_view name, double fallback) {
        for (std::size_t index = 0; index < header.vertexProperties.size(); ++index)
            if (header.vertexProperties[index].name == name)
                return values[index];
        return fallback;
    };
    ProxyVertex vertex;
    const std::array positions{value("x", 0), value("y", 0), value("z", 0)};
    const std::array normals{value("nx", 0), value("ny", 0), value("nz", 0)};
    for (std::size_t axis = 0; axis < 3; ++axis) {
        if (!std::isfinite(positions[axis]) || std::abs(positions[axis]) > 1.0e12 ||
            !std::isfinite(normals[axis]))
            return fail(ErrorCode::corruptData, "Proxy PLY vertex is non-finite or out of range");
        vertex.position[axis] = static_cast<float>(positions[axis]);
    }
    const double normalLength =
        std::sqrt(normals[0] * normals[0] + normals[1] * normals[1] + normals[2] * normals[2]);
    if (!std::isfinite(normalLength) || normalLength < 1.0e-12)
        return fail(ErrorCode::corruptData, "Proxy PLY vertex normal is degenerate");
    for (std::size_t axis = 0; axis < 3; ++axis)
        vertex.normal[axis] = static_cast<float>(normals[axis] / normalLength);
    std::array<std::uint32_t, 4> rgba{255, 255, 255, 255};
    constexpr std::array colorNames{"red", "green", "blue", "alpha"};
    for (std::size_t channel = 0; channel < colorNames.size(); ++channel) {
        const double component = value(colorNames[channel], 255);
        if (!std::isfinite(component) || component < 0 || component > 255 ||
            std::floor(component) != component)
            return fail(ErrorCode::corruptData, "Proxy PLY vertex color is invalid");
        rgba[channel] = static_cast<std::uint32_t>(component);
    }
    vertex.colorRgba = rgba[0] | (rgba[1] << 8U) | (rgba[2] << 16U) | (rgba[3] << 24U);
    return vertex;
}
} // namespace

Result<ProxyMesh> ProxyPlyLoader::load(const std::filesystem::path& path,
                                       const ProxyPlyLimits& limits) {
    std::error_code error;
    const auto fileBytes = std::filesystem::file_size(path, error);
    if (error || fileBytes == 0 || fileBytes > limits.maximumFileBytes)
        return fail(ErrorCode::invalidArgument, "Proxy PLY file size is invalid", path.string());
    std::ifstream stream(path, std::ios::binary);
    if (!stream)
        return fail(ErrorCode::notFound, "Unable to open proxy PLY", path.string());
    auto header = readHeader(stream, limits);
    if (!header)
        return std::unexpected(header.error());
    ProxyMesh mesh;
    mesh.vertices.reserve(header->vertexCount);
    mesh.indices.reserve(header->faceCount * 3U);
    std::vector<double> values(header->vertexProperties.size());
    for (std::size_t vertexIndex = 0; vertexIndex < header->vertexCount; ++vertexIndex) {
        if (header->format == Format::ascii) {
            std::string line;
            if (!std::getline(stream, line))
                return fail(ErrorCode::corruptData, "Proxy PLY vertex payload is truncated");
            std::istringstream tokens(line);
            for (double& scalar : values)
                if (!(tokens >> scalar))
                    return fail(ErrorCode::corruptData, "Proxy PLY vertex record is incomplete");
            std::string extra;
            if (tokens >> extra)
                return fail(ErrorCode::corruptData, "Proxy PLY vertex record has extra fields");
        } else {
            for (std::size_t property = 0; property < values.size(); ++property) {
                auto scalar = readBinaryScalar(stream, header->vertexProperties[property].type);
                if (!scalar)
                    return std::unexpected(scalar.error());
                values[property] = *scalar;
            }
        }
        auto vertex = makeVertex(*header, values);
        if (!vertex)
            return std::unexpected(vertex.error());
        mesh.vertices.push_back(*vertex);
    }
    for (std::size_t faceIndex = 0; faceIndex < header->faceCount; ++faceIndex) {
        std::array<double, 4> face{};
        if (header->format == Format::ascii) {
            std::string line;
            if (!std::getline(stream, line))
                return fail(ErrorCode::corruptData, "Proxy PLY face payload is truncated");
            std::istringstream tokens(line);
            if (!(tokens >> face[0] >> face[1] >> face[2] >> face[3]))
                return fail(ErrorCode::corruptData, "Proxy PLY face record is incomplete");
            std::string extra;
            if (tokens >> extra)
                return fail(ErrorCode::corruptData, "Proxy PLY face record has extra fields");
        } else {
            auto count = readBinaryScalar(stream, header->faceCountType);
            if (!count)
                return std::unexpected(count.error());
            face[0] = *count;
            if (face[0] != 3.0)
                return fail(ErrorCode::unsupported, "Proxy PLY contains a non-triangle face");
            for (std::size_t index = 1; index < face.size(); ++index) {
                auto scalar = readBinaryScalar(stream, header->faceIndexType);
                if (!scalar)
                    return std::unexpected(scalar.error());
                face[index] = *scalar;
            }
        }
        if (face[0] != 3.0)
            return fail(ErrorCode::unsupported, "Proxy PLY contains a non-triangle face");
        std::array<std::uint32_t, 3> triangle{};
        for (std::size_t index = 1; index < face.size(); ++index) {
            auto converted = scalarIndex(face[index], mesh.vertices.size());
            if (!converted)
                return std::unexpected(converted.error());
            triangle[index - 1] = *converted;
        }
        if (triangle[0] == triangle[1] || triangle[0] == triangle[2] || triangle[1] == triangle[2])
            return fail(ErrorCode::corruptData, "Proxy PLY contains a degenerate triangle");
        mesh.indices.insert(mesh.indices.end(), triangle.begin(), triangle.end());
    }
    if (stream.peek() != std::char_traits<char>::eof())
        return fail(ErrorCode::corruptData, "Proxy PLY has trailing payload data");
    return mesh;
}

} // namespace aether::hybrid
