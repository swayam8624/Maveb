#include <aether/mesh/PlyExporter.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <limits>
#include <tuple>
#include <vector>

#include <simd/simd.h>

namespace aether::mesh {
namespace {

struct ExportVertex final {
    simd_float3 position{};
    simd_float3 normal{};
    std::array<std::uint8_t, 3> color{};
};

std::uint8_t encodeColor(float value) {
    if (!std::isfinite(value))
        return 0;
    return static_cast<std::uint8_t>(
        std::lround(std::clamp(value, 0.0F, 1.0F) * 255.0F));
}

bool finite(simd_float3 value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}

} // namespace

Result<void> exportToPly(const MeshAsset& asset, const std::filesystem::path& path) {
    if (asset.primitives.empty())
        return fail(ErrorCode::invalidArgument, "Cannot export a mesh with no primitives");
    if (path.empty())
        return fail(ErrorCode::invalidArgument, "PLY output path is empty");

    std::vector<MeshInstance> instances = asset.instances;
    if (instances.empty()) {
        instances.reserve(asset.primitives.size());
        for (std::size_t primitive = 0; primitive < asset.primitives.size(); ++primitive) {
            MeshInstance instance;
            instance.primitiveIndex = primitive;
            instances.push_back(instance);
        }
    }

    std::vector<ExportVertex> vertices;
    std::vector<std::array<std::uint32_t, 3>> triangles;
    for (const auto& instance : instances) {
        if (instance.primitiveIndex >= asset.primitives.size())
            return fail(ErrorCode::corruptData, "Mesh instance references an invalid primitive");
        const auto& primitive = asset.primitives[instance.primitiveIndex];
        if (!primitive.vertexColors.empty() &&
            primitive.vertexColors.size() != primitive.vertices.size())
            return fail(ErrorCode::corruptData,
                        "Mesh vertex-color count does not match vertex count");
        if (primitive.indices.size() % 3 != 0)
            return fail(ErrorCode::corruptData, "Mesh index count is not divisible by three");
        if (primitive.vertices.size() >
            std::numeric_limits<std::uint32_t>::max() - vertices.size())
            return fail(ErrorCode::resourceExhausted, "PLY vertex count exceeds uint32");
        const auto baseVertex = static_cast<std::uint32_t>(vertices.size());
        const auto determinant = simd_determinant(instance.worldTransform);
        if (!std::isfinite(determinant) || std::abs(determinant) < 1.0e-12F)
            return fail(ErrorCode::corruptData, "Mesh instance transform is singular");
        const auto normalTransform = simd_transpose(simd_inverse(instance.worldTransform));
        for (std::size_t index = 0; index < primitive.vertices.size(); ++index) {
            const auto& source = primitive.vertices[index];
            const auto transformedPosition =
                simd_mul(instance.worldTransform, simd_make_float4(source.position, 1.0F)).xyz;
            auto transformedNormal =
                simd_mul(normalTransform, simd_make_float4(source.normal, 0.0F)).xyz;
            if (simd_length_squared(transformedNormal) <= 1.0e-20F)
                transformedNormal = simd_make_float3(0.0F, 0.0F, 1.0F);
            else
                transformedNormal = simd_normalize(transformedNormal);
            if (!finite(transformedPosition) || !finite(transformedNormal))
                return fail(ErrorCode::corruptData, "Mesh contains non-finite geometry");
            const auto color = primitive.vertexColors.empty()
                                   ? simd_make_float3(1.0F, 1.0F, 1.0F)
                                   : primitive.vertexColors[index];
            vertices.push_back(ExportVertex{
                transformedPosition,
                transformedNormal,
                {encodeColor(color.x), encodeColor(color.y), encodeColor(color.z)},
            });
        }
        for (std::size_t index = 0; index < primitive.indices.size(); index += 3) {
            const auto a = primitive.indices[index];
            const auto b = primitive.indices[index + 1];
            const auto c = primitive.indices[index + 2];
            if (a >= primitive.vertices.size() || b >= primitive.vertices.size() ||
                c >= primitive.vertices.size())
                return fail(ErrorCode::corruptData, "Mesh contains an out-of-range index");
            if (a == b || b == c || a == c)
                return fail(ErrorCode::corruptData, "Mesh contains a degenerate index triangle");
            triangles.push_back(
                determinant < 0.0F
                    ? std::array<std::uint32_t, 3>{baseVertex + a, baseVertex + c,
                                                   baseVertex + b}
                    : std::array<std::uint32_t, 3>{baseVertex + a, baseVertex + b,
                                                   baseVertex + c});
        }
    }
    if (vertices.empty() || triangles.empty())
        return fail(ErrorCode::invalidArgument, "Cannot export an empty PLY surface");

    auto temporary = path;
    temporary += ".tmp";
    std::error_code filesystemError;
    std::filesystem::remove(temporary, filesystemError);
    std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
    if (!output)
        return fail(ErrorCode::io, "Unable to create temporary PLY", temporary.string());
    output << "ply\nformat binary_little_endian 1.0\n"
              "comment generated by AETHER deterministic exporter\n"
           << "element vertex " << vertices.size()
           << "\nproperty float x\nproperty float y\nproperty float z\n"
              "property float nx\nproperty float ny\nproperty float nz\n"
              "property uchar red\nproperty uchar green\nproperty uchar blue\n"
           << "element face " << triangles.size()
           << "\nproperty list uchar uint vertex_indices\nend_header\n";
    for (const auto& vertex : vertices) {
        const std::array<float, 6> attributes{
            vertex.position.x, vertex.position.y, vertex.position.z,
            vertex.normal.x, vertex.normal.y, vertex.normal.z};
        output.write(reinterpret_cast<const char*>(attributes.data()),
                     static_cast<std::streamsize>(sizeof(attributes)));
        output.write(reinterpret_cast<const char*>(vertex.color.data()),
                     static_cast<std::streamsize>(vertex.color.size()));
    }
    for (const auto& triangle : triangles) {
        constexpr std::uint8_t count = 3;
        output.write(reinterpret_cast<const char*>(&count), sizeof(count));
        output.write(reinterpret_cast<const char*>(triangle.data()),
                     static_cast<std::streamsize>(triangle.size() *
                                                  sizeof(triangle.front())));
    }
    output.flush();
    if (!output.good()) {
        output.close();
        std::filesystem::remove(temporary, filesystemError);
        return fail(ErrorCode::io, "Unable to write complete PLY", path.string());
    }
    output.close();
    std::filesystem::rename(temporary, path, filesystemError);
    if (filesystemError) {
        std::filesystem::remove(path, filesystemError);
        filesystemError.clear();
        std::filesystem::rename(temporary, path, filesystemError);
    }
    if (filesystemError) {
        std::filesystem::remove(temporary, filesystemError);
        return fail(ErrorCode::io, "Unable to publish PLY atomically", path.string());
    }
    return {};
}

} // namespace aether::mesh
