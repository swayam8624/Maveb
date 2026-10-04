#include <aether/hybrid/ProxyMeshCodec.hpp>

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <limits>

namespace aether::hybrid {
namespace {
constexpr std::array<std::byte, 8> magic{std::byte{'A'}, std::byte{'E'}, std::byte{'T'},
                                         std::byte{'H'}, std::byte{'P'}, std::byte{'X'},
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

Result<void> validateVertex(const ProxyVertex& vertex) {
    auto finite = [](float value) { return std::isfinite(value) && std::abs(value) <= 1.0e12F; };
    if (!std::ranges::all_of(vertex.position, finite) ||
        !std::ranges::all_of(vertex.normal, finite) || !std::isfinite(vertex.confidence) ||
        vertex.confidence < 0.0F || vertex.confidence > 1.0F)
        return fail(ErrorCode::corruptData, "Proxy vertex contains an unsafe value");
    double lengthSquared = 0.0;
    for (const float value : vertex.normal)
        lengthSquared += static_cast<double>(value) * value;
    if (lengthSquared < 0.999 || lengthSquared > 1.001)
        return fail(ErrorCode::corruptData, "Proxy vertex normal is not normalized");
    return {};
}

Result<void> validateMesh(const ProxyMesh& mesh) {
    if (mesh.vertices.size() < 3 || mesh.indices.empty() || mesh.indices.size() % 3 != 0)
        return fail(ErrorCode::invalidArgument, "Proxy mesh is empty or not triangulated");
    for (const auto& vertex : mesh.vertices)
        if (auto valid = validateVertex(vertex); !valid)
            return valid;
    for (const auto index : mesh.indices)
        if (index >= mesh.vertices.size())
            return fail(ErrorCode::corruptData, "Proxy triangle index is outside the vertex array");
    for (std::size_t index = 0; index < mesh.indices.size(); index += 3)
        if (mesh.indices[index] == mesh.indices[index + 1] ||
            mesh.indices[index] == mesh.indices[index + 2] ||
            mesh.indices[index + 1] == mesh.indices[index + 2])
            return fail(ErrorCode::corruptData, "Proxy mesh contains a degenerate triangle");
    return {};
}
} // namespace

Result<std::vector<std::byte>> ProxyMeshCodec::encode(const ProxyMesh& mesh) {
    if (auto valid = validateMesh(mesh); !valid)
        return std::unexpected(valid.error());
    if (mesh.vertices.size() > std::numeric_limits<std::uint32_t>::max() ||
        mesh.indices.size() > std::numeric_limits<std::uint32_t>::max() ||
        mesh.vertices.size() >
            (std::numeric_limits<std::size_t>::max() - headerBytes) / vertexBytes)
        return fail(ErrorCode::resourceExhausted, "Proxy mesh dimensions overflow the codec");
    const std::size_t vertexPayload = mesh.vertices.size() * vertexBytes;
    if (mesh.indices.size() >
        (std::numeric_limits<std::size_t>::max() - headerBytes - vertexPayload) /
            sizeof(std::uint32_t))
        return fail(ErrorCode::resourceExhausted, "Proxy index payload overflows the codec");
    std::vector<std::byte> output;
    output.reserve(headerBytes + vertexPayload + mesh.indices.size() * sizeof(std::uint32_t));
    output.insert(output.end(), magic.begin(), magic.end());
    append16(output, 1);
    append16(output, 0);
    append32(output, vertexBytes);
    append64(output, mesh.vertices.size());
    append64(output, mesh.indices.size());
    for (const auto& vertex : mesh.vertices) {
        for (const float value : vertex.position)
            appendFloat(output, value);
        for (const float value : vertex.normal)
            appendFloat(output, value);
        appendFloat(output, vertex.confidence);
        append32(output, vertex.colorRgba);
    }
    for (const auto index : mesh.indices)
        append32(output, index);
    return output;
}

Result<ProxyMesh> ProxyMeshCodec::decode(std::span<const std::byte> bytes,
                                         std::size_t maximumVertices,
                                         std::size_t maximumTriangles) {
    if (bytes.size() < headerBytes || !std::equal(magic.begin(), magic.end(), bytes.begin()))
        return fail(ErrorCode::corruptData, "Canonical proxy chunk magic is invalid");
    if (read16(bytes.data() + 8) != 1)
        return fail(ErrorCode::unsupported, "Canonical proxy chunk major version is unsupported");
    const std::uint32_t stride = read32(bytes.data() + 12);
    const std::uint64_t vertexCount = read64(bytes.data() + 16);
    const std::uint64_t indexCount = read64(bytes.data() + 24);
    if (stride != vertexBytes || vertexCount < 3 || vertexCount > maximumVertices ||
        indexCount == 0 || indexCount % 3 != 0 || indexCount / 3 > maximumTriangles ||
        vertexCount > (bytes.size() - headerBytes) / vertexBytes)
        return fail(ErrorCode::corruptData, "Canonical proxy chunk dimensions are invalid");
    const std::uint64_t expected = headerBytes + vertexCount * vertexBytes + indexCount * 4U;
    if (expected != bytes.size())
        return fail(ErrorCode::corruptData, "Canonical proxy chunk byte size is inconsistent");
    ProxyMesh mesh;
    mesh.vertices.resize(static_cast<std::size_t>(vertexCount));
    const std::byte* cursor = bytes.data() + headerBytes;
    for (auto& vertex : mesh.vertices) {
        for (float& value : vertex.position) {
            value = readFloat(cursor);
            cursor += 4;
        }
        for (float& value : vertex.normal) {
            value = readFloat(cursor);
            cursor += 4;
        }
        vertex.confidence = readFloat(cursor);
        cursor += 4;
        vertex.colorRgba = read32(cursor);
        cursor += 4;
    }
    mesh.indices.resize(static_cast<std::size_t>(indexCount));
    for (auto& index : mesh.indices) {
        index = read32(cursor);
        cursor += 4;
    }
    if (auto valid = validateMesh(mesh); !valid)
        return std::unexpected(valid.error());
    return mesh;
}

} // namespace aether::hybrid
