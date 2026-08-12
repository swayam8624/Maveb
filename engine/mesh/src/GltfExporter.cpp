#include <aether/mesh/GltfExporter.hpp>

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <iomanip>
#include <limits>
#include <locale>
#include <span>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

namespace aether::mesh {
namespace {

constexpr std::uint32_t glbMagic = 0x46546c67U;
constexpr std::uint32_t jsonChunkType = 0x4e4f534aU;
constexpr std::uint32_t binaryChunkType = 0x004e4942U;
constexpr std::uint32_t floatComponent = 5126;
constexpr std::uint32_t unsignedIntComponent = 5125;
constexpr std::uint32_t arrayBufferTarget = 34962;
constexpr std::uint32_t elementArrayBufferTarget = 34963;

struct BufferView final {
    std::uint64_t offset{};
    std::uint64_t bytes{};
    std::optional<std::uint32_t> target;
};

struct Accessor final {
    std::size_t bufferView{};
    std::uint32_t componentType{};
    std::size_t count{};
    std::string_view type;
    std::optional<std::array<float, 3>> minimum;
    std::optional<std::array<float, 3>> maximum;
};

struct PrimitiveExport final {
    std::size_t position{};
    std::size_t normal{};
    std::size_t tangent{};
    std::size_t textureCoordinate{};
    std::optional<std::size_t> color;
    std::size_t indices{};
};

struct ImageExport final {
    std::size_t bufferView{};
    std::string_view mimeType;
};

void append32(std::vector<std::byte>& output, std::uint32_t value) {
    for (std::uint32_t shift = 0; shift < 32; shift += 8)
        output.push_back(static_cast<std::byte>((value >> shift) & 0xffU));
}

void appendFloat(std::vector<std::byte>& output, float value) {
    append32(output, std::bit_cast<std::uint32_t>(value));
}

void align4(std::vector<std::byte>& output) {
    output.insert(output.end(), (4U - output.size() % 4U) % 4U, std::byte{0});
}

bool finite(simd_float2 value) {
    return std::isfinite(value.x) && std::isfinite(value.y);
}

bool finite(simd_float3 value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}

bool finite(simd_float4 value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z) &&
           std::isfinite(value.w);
}

bool finite(simd_float4x4 value) {
    for (std::size_t column = 0; column < 4; ++column)
        if (!finite(value.columns[column]))
            return false;
    return true;
}

std::string escapeJson(std::string_view value) {
    std::string result;
    result.reserve(value.size());
    constexpr char hexadecimal[] = "0123456789abcdef";
    for (const char rawCharacter : value) {
        const auto character = static_cast<unsigned char>(rawCharacter);
        switch (character) {
        case '"':
            result += "\\\"";
            break;
        case '\\':
            result += "\\\\";
            break;
        case '\b':
            result += "\\b";
            break;
        case '\f':
            result += "\\f";
            break;
        case '\n':
            result += "\\n";
            break;
        case '\r':
            result += "\\r";
            break;
        case '\t':
            result += "\\t";
            break;
        default:
            if (character < 0x20U) {
                result += "\\u00";
                result += hexadecimal[(character >> 4U) & 0x0fU];
                result += hexadecimal[character & 0x0fU];
            } else {
                result += static_cast<char>(character);
            }
        }
    }
    return result;
}

Result<std::string_view> imageMimeType(std::span<const std::byte> bytes) {
    constexpr std::array pngMagic{std::byte{0x89}, std::byte{'P'},  std::byte{'N'},
                                  std::byte{'G'},  std::byte{0x0d}, std::byte{0x0a},
                                  std::byte{0x1a}, std::byte{0x0a}};
    if (bytes.size() >= pngMagic.size() &&
        std::equal(pngMagic.begin(), pngMagic.end(), bytes.begin()))
        return "image/png";
    if (bytes.size() >= 3 && bytes[0] == std::byte{0xff} && bytes[1] == std::byte{0xd8} &&
        bytes[2] == std::byte{0xff})
        return "image/jpeg";
    return fail(ErrorCode::unsupported,
                "Native GLB export supports embedded PNG and JPEG textures only");
}

std::uint32_t wrapMode(SamplerAddressMode mode) {
    switch (mode) {
    case SamplerAddressMode::clampToEdge:
        return 33071;
    case SamplerAddressMode::mirroredRepeat:
        return 33648;
    case SamplerAddressMode::repeat:
        return 10497;
    }
    return 10497;
}

std::uint32_t magnificationFilter(SamplerFilter filter) {
    return filter == SamplerFilter::nearest ? 9728 : 9729;
}

std::uint32_t minificationFilter(const TextureAsset& texture) {
    if (texture.mipFilter == SamplerMipFilter::none)
        return texture.minification == SamplerFilter::nearest ? 9728 : 9729;
    if (texture.mipFilter == SamplerMipFilter::nearest)
        return texture.minification == SamplerFilter::nearest ? 9984 : 9985;
    return texture.minification == SamplerFilter::nearest ? 9986 : 9987;
}

bool nonIdentity(const PbrMaterial::UvTransform& transform) {
    return transform.scale.x != 1.0F || transform.scale.y != 1.0F || transform.offset.x != 0.0F ||
           transform.offset.y != 0.0F || transform.rotation != 0.0F;
}

Result<void> validateMaterial(const PbrMaterial& material, std::size_t textureCount) {
    if (!finite(material.baseColor) || !finite(material.emissive) ||
        !std::isfinite(material.metallic) || !std::isfinite(material.roughness) ||
        !std::isfinite(material.normalScale) || !std::isfinite(material.occlusionStrength) ||
        !std::isfinite(material.alphaCutoff) || material.metallic < 0.0F ||
        material.metallic > 1.0F || material.roughness < 0.0F || material.roughness > 1.0F ||
        material.normalScale < 0.0F || material.occlusionStrength < 0.0F ||
        material.occlusionStrength > 1.0F || material.alphaCutoff < 0.0F ||
        material.alphaCutoff > 1.0F || (material.alphaBlend && material.alphaMask))
        return fail(ErrorCode::corruptData, "Mesh material factors are invalid", material.name);
    const std::array bindings{material.baseColorTexture, material.metallicRoughnessTexture,
                              material.normalTexture, material.occlusionTexture,
                              material.emissiveTexture};
    for (std::size_t slot = 0; slot < bindings.size(); ++slot) {
        const auto binding = bindings[slot];
        if (binding.has_value()) {
            const auto textureIndex = binding.value();
            if (textureIndex >= textureCount)
                return fail(ErrorCode::corruptData, "Mesh material texture index is invalid",
                            material.name);
        }
        const auto& transform = material.uvTransforms[slot];
        if (!finite(transform.scale) || !finite(transform.offset) ||
            !std::isfinite(transform.rotation))
            return fail(ErrorCode::corruptData, "Mesh material UV transform is not finite",
                        material.name);
    }
    return {};
}

Result<void> checkGrowth(std::uint64_t current, std::uint64_t additional, std::uint64_t limit,
                         std::string_view purpose) {
    if (additional > limit || current > limit - additional)
        return fail(ErrorCode::resourceExhausted, "Native GLB export exceeds its byte budget",
                    std::string(purpose));
    return {};
}

template <typename Writer>
Result<std::size_t> appendBufferView(std::vector<std::byte>& binary, std::vector<BufferView>& views,
                                     std::uint64_t bytes, std::optional<std::uint32_t> target,
                                     std::uint64_t limit, Writer&& writer) {
    align4(binary);
    if (auto growth = checkGrowth(binary.size(), bytes, limit, "binary buffer"); !growth)
        return std::unexpected(growth.error());
    const std::size_t viewIndex = views.size();
    views.push_back(BufferView{binary.size(), bytes, target});
    binary.reserve(binary.size() + static_cast<std::size_t>(bytes));
    writer(binary);
    if (binary.size() != views.back().offset + bytes)
        return fail(ErrorCode::internal, "Native GLB attribute writer produced an invalid size");
    return viewIndex;
}

void writeTextureBinding(std::ostringstream& json, std::string_view name,
                         const std::optional<std::size_t>& texture,
                         const PbrMaterial::UvTransform& transform, bool& first,
                         std::optional<float> scalar = std::nullopt,
                         std::string_view scalarName = {}) {
    if (!texture)
        return;
    if (!first)
        json << ',';
    first = false;
    json << '"' << name << "\":{\"index\":" << *texture;
    if (scalar)
        json << ",\"" << scalarName << "\":" << *scalar;
    if (nonIdentity(transform)) {
        json << ",\"extensions\":{\"KHR_texture_transform\":{\"offset\":[" << transform.offset.x
             << ',' << transform.offset.y << "],\"rotation\":" << transform.rotation
             << ",\"scale\":[" << transform.scale.x << ',' << transform.scale.y << "]}}";
    }
    json << '}';
}

} // namespace

Result<GltfExportReport> GltfExporter::writeGlb(const MeshAsset& asset,
                                                const std::filesystem::path& destination,
                                                const GltfExportLimits& limits) {
    if (destination.empty())
        return fail(ErrorCode::invalidArgument, "GLB destination is empty");
    if (asset.primitives.empty() || asset.primitives.size() > limits.maximumPrimitives)
        return fail(ErrorCode::invalidArgument, "GLB export requires a bounded mesh primitive set");
    if (!asset.animations.empty() || !asset.skins.empty())
        return fail(
            ErrorCode::unsupported,
            "Native GLB reconstruction export does not silently discard animation or skins");
    if (asset.images.size() > limits.maximumImages)
        return fail(ErrorCode::resourceExhausted, "GLB image count exceeds its limit");

    std::uint64_t totalImageBytes{};
    std::vector<std::string_view> imageMimeTypes;
    imageMimeTypes.reserve(asset.images.size());
    for (const auto& image : asset.images) {
        if (image.bytes.empty() || image.bytes.size() > limits.maximumImageBytes ||
            totalImageBytes > limits.maximumImageBytes - image.bytes.size())
            return fail(ErrorCode::resourceExhausted, "GLB image payload exceeds its limit",
                        image.name);
        auto mimeType = imageMimeType(image.bytes);
        if (!mimeType)
            return std::unexpected(mimeType.error());
        imageMimeTypes.push_back(*mimeType);
        totalImageBytes += image.bytes.size();
    }
    for (const auto& texture : asset.textures)
        if (texture.imageIndex >= asset.images.size())
            return fail(ErrorCode::corruptData, "Mesh texture references an invalid image");
    for (const auto& material : asset.materials)
        if (auto validated = validateMaterial(material, asset.textures.size()); !validated)
            return std::unexpected(validated.error());

    std::vector<MeshInstance> instances = asset.instances;
    if (instances.empty()) {
        instances.reserve(asset.primitives.size());
        for (std::size_t primitive = 0; primitive < asset.primitives.size(); ++primitive) {
            MeshInstance instance;
            instance.name = asset.primitives[primitive].name;
            instance.primitiveIndex = primitive;
            instances.push_back(std::move(instance));
        }
    }
    if (instances.empty() || instances.size() > limits.maximumInstances)
        return fail(ErrorCode::resourceExhausted, "GLB instance count exceeds its limit");
    for (const auto& instance : instances) {
        if (instance.primitiveIndex >= asset.primitives.size())
            return fail(ErrorCode::corruptData, "Mesh instance references an invalid primitive");
        if (instance.skinIndex || !instance.morphWeights.empty())
            return fail(ErrorCode::unsupported,
                        "Native GLB reconstruction export does not silently discard deformation");
        const float determinant = simd_determinant(instance.worldTransform);
        if (!finite(instance.worldTransform) || !std::isfinite(determinant) ||
            std::abs(determinant) <= 1.0e-12F)
            return fail(ErrorCode::corruptData, "Mesh instance transform is non-finite or singular",
                        instance.name);
    }

    std::vector<std::byte> binary;
    std::vector<BufferView> bufferViews;
    std::vector<Accessor> accessors;
    std::vector<PrimitiveExport> primitiveExports;
    primitiveExports.reserve(asset.primitives.size());
    std::size_t totalVertices{};
    std::size_t totalIndices{};
    for (const auto& primitive : asset.primitives) {
        if (primitive.vertices.empty() || primitive.indices.empty() ||
            primitive.indices.size() % 3 != 0)
            return fail(ErrorCode::corruptData, "Mesh primitive has invalid triangle geometry",
                        primitive.name);
        if (primitive.hasSkinAttributes || !primitive.morphTargets.empty() ||
            !primitive.defaultMorphWeights.empty())
            return fail(ErrorCode::unsupported,
                        "Native GLB reconstruction export does not silently discard deformation",
                        primitive.name);
        if ((!asset.materials.empty() && primitive.materialIndex >= asset.materials.size()) ||
            (asset.materials.empty() && primitive.materialIndex != 0))
            return fail(ErrorCode::corruptData, "Mesh primitive material index is invalid",
                        primitive.name);
        if (!primitive.vertexColors.empty() &&
            primitive.vertexColors.size() != primitive.vertices.size())
            return fail(ErrorCode::corruptData, "Mesh vertex-color count does not match vertices",
                        primitive.name);
        if (primitive.vertices.size() > limits.maximumVertices - totalVertices ||
            primitive.indices.size() > limits.maximumIndices - totalIndices)
            return fail(ErrorCode::resourceExhausted, "GLB geometry exceeds its allocation limit");
        totalVertices += primitive.vertices.size();
        totalIndices += primitive.indices.size();

        std::array<float, 3> minimum{primitive.vertices.front().position.x,
                                     primitive.vertices.front().position.y,
                                     primitive.vertices.front().position.z};
        std::array<float, 3> maximum = minimum;
        for (const auto& vertex : primitive.vertices) {
            if (!finite(vertex.position) || !finite(vertex.normal) || !finite(vertex.tangent) ||
                !finite(vertex.textureCoordinate) ||
                simd_length_squared(vertex.normal) <= 1.0e-20F ||
                simd_length_squared(vertex.tangent.xyz) <= 1.0e-20F)
                return fail(ErrorCode::corruptData, "Mesh vertex attributes are invalid",
                            primitive.name);
            minimum[0] = std::min(minimum[0], vertex.position.x);
            minimum[1] = std::min(minimum[1], vertex.position.y);
            minimum[2] = std::min(minimum[2], vertex.position.z);
            maximum[0] = std::max(maximum[0], vertex.position.x);
            maximum[1] = std::max(maximum[1], vertex.position.y);
            maximum[2] = std::max(maximum[2], vertex.position.z);
        }
        if (std::ranges::any_of(primitive.vertexColors,
                                [](simd_float3 color) { return !finite(color); }))
            return fail(ErrorCode::corruptData, "Mesh vertex color is not finite", primitive.name);
        for (std::size_t index = 0; index < primitive.indices.size(); index += 3) {
            const auto first = primitive.indices[index];
            const auto second = primitive.indices[index + 1];
            const auto third = primitive.indices[index + 2];
            if (first >= primitive.vertices.size() || second >= primitive.vertices.size() ||
                third >= primitive.vertices.size() || first == second || second == third ||
                first == third)
                return fail(ErrorCode::corruptData, "Mesh triangle indices are invalid",
                            primitive.name);
            const auto edge1 =
                primitive.vertices[second].position - primitive.vertices[first].position;
            const auto edge2 =
                primitive.vertices[third].position - primitive.vertices[first].position;
            if (simd_length_squared(simd_cross(edge1, edge2)) <= 1.0e-20F)
                return fail(ErrorCode::corruptData, "Mesh contains a zero-area triangle",
                            primitive.name);
        }

        PrimitiveExport exported;
        auto appendAttribute =
            [&](std::size_t components, const auto& valueWriter, std::string_view type,
                std::optional<std::array<float, 3>> attributeMinimum = {},
                std::optional<std::array<float, 3>> attributeMaximum = {}) -> Result<std::size_t> {
            const std::uint64_t bytes = primitive.vertices.size() * components * sizeof(float);
            auto view = appendBufferView(binary, bufferViews, bytes, arrayBufferTarget,
                                         limits.maximumOutputBytes, valueWriter);
            if (!view)
                return std::unexpected(view.error());
            const std::size_t accessor = accessors.size();
            accessors.push_back(Accessor{*view, floatComponent, primitive.vertices.size(), type,
                                         attributeMinimum, attributeMaximum});
            return accessor;
        };
        auto position = appendAttribute(
            3,
            [&](auto& output) {
                for (const auto& vertex : primitive.vertices) {
                    appendFloat(output, vertex.position.x);
                    appendFloat(output, vertex.position.y);
                    appendFloat(output, vertex.position.z);
                }
            },
            "VEC3", minimum, maximum);
        auto normal = appendAttribute(
            3,
            [&](auto& output) {
                for (const auto& vertex : primitive.vertices) {
                    appendFloat(output, vertex.normal.x);
                    appendFloat(output, vertex.normal.y);
                    appendFloat(output, vertex.normal.z);
                }
            },
            "VEC3");
        auto tangent = appendAttribute(
            4,
            [&](auto& output) {
                for (const auto& vertex : primitive.vertices) {
                    appendFloat(output, vertex.tangent.x);
                    appendFloat(output, vertex.tangent.y);
                    appendFloat(output, vertex.tangent.z);
                    appendFloat(output, vertex.tangent.w);
                }
            },
            "VEC4");
        auto textureCoordinate = appendAttribute(
            2,
            [&](auto& output) {
                for (const auto& vertex : primitive.vertices) {
                    appendFloat(output, vertex.textureCoordinate.x);
                    appendFloat(output, vertex.textureCoordinate.y);
                }
            },
            "VEC2");
        if (!position || !normal || !tangent || !textureCoordinate)
            return fail(ErrorCode::internal, "Unable to append GLB mesh attributes");
        exported.position = *position;
        exported.normal = *normal;
        exported.tangent = *tangent;
        exported.textureCoordinate = *textureCoordinate;
        if (!primitive.vertexColors.empty()) {
            auto color = appendAttribute(
                3,
                [&](auto& output) {
                    for (const auto value : primitive.vertexColors) {
                        appendFloat(output, value.x);
                        appendFloat(output, value.y);
                        appendFloat(output, value.z);
                    }
                },
                "VEC3");
            if (!color)
                return std::unexpected(color.error());
            exported.color = *color;
        }
        const std::uint64_t indexBytes = primitive.indices.size() * sizeof(std::uint32_t);
        auto indexView = appendBufferView(binary, bufferViews, indexBytes, elementArrayBufferTarget,
                                          limits.maximumOutputBytes, [&](auto& output) {
                                              for (const auto index : primitive.indices)
                                                  append32(output, index);
                                          });
        if (!indexView)
            return std::unexpected(indexView.error());
        exported.indices = accessors.size();
        accessors.push_back(
            Accessor{*indexView, unsignedIntComponent, primitive.indices.size(), "SCALAR", {}, {}});
        primitiveExports.push_back(exported);
    }

    std::vector<ImageExport> imageExports;
    imageExports.reserve(asset.images.size());
    for (std::size_t index = 0; index < asset.images.size(); ++index) {
        const auto& image = asset.images[index];
        auto view = appendBufferView(binary, bufferViews, image.bytes.size(), std::nullopt,
                                     limits.maximumOutputBytes, [&](auto& output) {
                                         output.insert(output.end(), image.bytes.begin(),
                                                       image.bytes.end());
                                     });
        if (!view)
            return std::unexpected(view.error());
        imageExports.push_back(ImageExport{*view, imageMimeTypes[index]});
    }
    align4(binary);

    const bool usesTextureTransform =
        std::ranges::any_of(asset.materials, [](const auto& material) {
            return std::ranges::any_of(material.uvTransforms, nonIdentity);
        });
    std::ostringstream json;
    json.imbue(std::locale::classic());
    json << std::setprecision(std::numeric_limits<float>::max_digits10);
    json << "{\"asset\":{\"version\":\"2.0\",\"generator\":\"Maveb native GLB exporter\"}";
    if (usesTextureTransform)
        json << ",\"extensionsUsed\":[\"KHR_texture_transform\"]";
    json << ",\"scene\":0,\"scenes\":[{\"nodes\":[";
    for (std::size_t index = 0; index < instances.size(); ++index) {
        if (index > 0)
            json << ',';
        json << index;
    }
    json << "]}],\"nodes\":[";
    for (std::size_t index = 0; index < instances.size(); ++index) {
        if (index > 0)
            json << ',';
        const auto& instance = instances[index];
        json << "{\"name\":\"" << escapeJson(instance.name)
             << "\",\"mesh\":" << instance.primitiveIndex << ",\"matrix\":[";
        bool first = true;
        for (std::size_t column = 0; column < 4; ++column)
            for (std::size_t row = 0; row < 4; ++row) {
                if (!first)
                    json << ',';
                first = false;
                json << instance.worldTransform.columns[column][row];
            }
        json << "]}";
    }
    json << "],\"meshes\":[";
    for (std::size_t index = 0; index < asset.primitives.size(); ++index) {
        if (index > 0)
            json << ',';
        const auto& primitive = asset.primitives[index];
        const auto& exported = primitiveExports[index];
        json << "{\"name\":\"" << escapeJson(primitive.name)
             << "\",\"primitives\":[{\"attributes\":{\"POSITION\":" << exported.position
             << ",\"NORMAL\":" << exported.normal << ",\"TANGENT\":" << exported.tangent
             << ",\"TEXCOORD_0\":" << exported.textureCoordinate;
        if (exported.color)
            json << ",\"COLOR_0\":" << *exported.color;
        json << "},\"indices\":" << exported.indices;
        if (primitive.materialIndex > 0)
            json << ",\"material\":" << primitive.materialIndex - 1;
        json << "}]}";
    }
    json << ']';

    if (asset.materials.size() > 1) {
        json << ",\"materials\":[";
        for (std::size_t index = 1; index < asset.materials.size(); ++index) {
            if (index > 1)
                json << ',';
            const auto& material = asset.materials[index];
            json << "{\"name\":\"" << escapeJson(material.name)
                 << "\",\"pbrMetallicRoughness\":{\"baseColorFactor\":[" << material.baseColor.x
                 << ',' << material.baseColor.y << ',' << material.baseColor.z << ','
                 << material.baseColor.w << "],\"metallicFactor\":" << material.metallic
                 << ",\"roughnessFactor\":" << material.roughness;
            if (material.baseColorTexture) {
                json << ",\"baseColorTexture\":{\"index\":" << *material.baseColorTexture;
                if (nonIdentity(material.uvTransforms[0])) {
                    const auto& transform = material.uvTransforms[0];
                    json << ",\"extensions\":{\"KHR_texture_transform\":{\"offset\":["
                         << transform.offset.x << ',' << transform.offset.y
                         << "],\"rotation\":" << transform.rotation << ",\"scale\":["
                         << transform.scale.x << ',' << transform.scale.y << "]}}";
                }
                json << '}';
            }
            if (material.metallicRoughnessTexture) {
                json << ",\"metallicRoughnessTexture\":{\"index\":"
                     << *material.metallicRoughnessTexture;
                if (nonIdentity(material.uvTransforms[1])) {
                    const auto& transform = material.uvTransforms[1];
                    json << ",\"extensions\":{\"KHR_texture_transform\":{\"offset\":["
                         << transform.offset.x << ',' << transform.offset.y
                         << "],\"rotation\":" << transform.rotation << ",\"scale\":["
                         << transform.scale.x << ',' << transform.scale.y << "]}}";
                }
                json << '}';
            }
            json << '}';
            bool firstProperty = false;
            writeTextureBinding(json, "normalTexture", material.normalTexture,
                                material.uvTransforms[2], firstProperty, material.normalScale,
                                "scale");
            writeTextureBinding(json, "occlusionTexture", material.occlusionTexture,
                                material.uvTransforms[3], firstProperty, material.occlusionStrength,
                                "strength");
            writeTextureBinding(json, "emissiveTexture", material.emissiveTexture,
                                material.uvTransforms[4], firstProperty);
            json << ",\"emissiveFactor\":[" << material.emissive.x << ',' << material.emissive.y
                 << ',' << material.emissive.z << ']';
            if (material.doubleSided)
                json << ",\"doubleSided\":true";
            if (material.alphaBlend)
                json << ",\"alphaMode\":\"BLEND\"";
            else if (material.alphaMask)
                json << ",\"alphaMode\":\"MASK\",\"alphaCutoff\":" << material.alphaCutoff;
            json << '}';
        }
        json << ']';
    }
    if (!asset.textures.empty()) {
        json << ",\"samplers\":[";
        for (std::size_t index = 0; index < asset.textures.size(); ++index) {
            if (index > 0)
                json << ',';
            const auto& texture = asset.textures[index];
            json << "{\"magFilter\":" << magnificationFilter(texture.magnification)
                 << ",\"minFilter\":" << minificationFilter(texture)
                 << ",\"wrapS\":" << wrapMode(texture.addressU)
                 << ",\"wrapT\":" << wrapMode(texture.addressV) << '}';
        }
        json << "],\"textures\":[";
        for (std::size_t index = 0; index < asset.textures.size(); ++index) {
            if (index > 0)
                json << ',';
            json << "{\"sampler\":" << index << ",\"source\":" << asset.textures[index].imageIndex
                 << '}';
        }
        json << ']';
    }
    if (!asset.images.empty()) {
        json << ",\"images\":[";
        for (std::size_t index = 0; index < asset.images.size(); ++index) {
            if (index > 0)
                json << ',';
            json << "{\"name\":\"" << escapeJson(asset.images[index].name)
                 << "\",\"bufferView\":" << imageExports[index].bufferView << ",\"mimeType\":\""
                 << imageExports[index].mimeType << "\"}";
        }
        json << ']';
    }
    json << ",\"buffers\":[{\"byteLength\":" << binary.size() << "}],\"bufferViews\":[";
    for (std::size_t index = 0; index < bufferViews.size(); ++index) {
        if (index > 0)
            json << ',';
        const auto& view = bufferViews[index];
        json << "{\"buffer\":0,\"byteOffset\":" << view.offset << ",\"byteLength\":" << view.bytes;
        if (view.target)
            json << ",\"target\":" << *view.target;
        json << '}';
    }
    json << "],\"accessors\":[";
    for (std::size_t index = 0; index < accessors.size(); ++index) {
        if (index > 0)
            json << ',';
        const auto& accessor = accessors[index];
        json << "{\"bufferView\":" << accessor.bufferView
             << ",\"componentType\":" << accessor.componentType << ",\"count\":" << accessor.count
             << ",\"type\":\"" << accessor.type << '"';
        if (accessor.minimum)
            json << ",\"min\":[" << (*accessor.minimum)[0] << ',' << (*accessor.minimum)[1] << ','
                 << (*accessor.minimum)[2] << ']';
        if (accessor.maximum)
            json << ",\"max\":[" << (*accessor.maximum)[0] << ',' << (*accessor.maximum)[1] << ','
                 << (*accessor.maximum)[2] << ']';
        json << '}';
    }
    json << "]}";

    std::string jsonBytes = json.str();
    jsonBytes.append((4U - jsonBytes.size() % 4U) % 4U, ' ');
    const std::uint64_t totalBytes = 12ULL + 8ULL + jsonBytes.size() + 8ULL + binary.size();
    if (totalBytes > limits.maximumOutputBytes ||
        totalBytes > std::numeric_limits<std::uint32_t>::max())
        return fail(ErrorCode::resourceExhausted, "GLB output exceeds 32-bit container limits");
    std::vector<std::byte> output;
    output.reserve(static_cast<std::size_t>(totalBytes));
    append32(output, glbMagic);
    append32(output, 2);
    append32(output, static_cast<std::uint32_t>(totalBytes));
    append32(output, static_cast<std::uint32_t>(jsonBytes.size()));
    append32(output, jsonChunkType);
    for (const char character : jsonBytes)
        output.push_back(static_cast<std::byte>(static_cast<unsigned char>(character)));
    append32(output, static_cast<std::uint32_t>(binary.size()));
    append32(output, binaryChunkType);
    output.insert(output.end(), binary.begin(), binary.end());

    auto temporary = destination;
    temporary += ".tmp";
    std::error_code filesystemError;
    std::filesystem::remove(temporary, filesystemError);
    filesystemError.clear();
    std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
    stream.write(reinterpret_cast<const char*>(output.data()),
                 static_cast<std::streamsize>(output.size()));
    stream.close();
    if (!stream) {
        std::filesystem::remove(temporary, filesystemError);
        return fail(ErrorCode::io, "Unable to write complete GLB", destination);
    }
    std::filesystem::rename(temporary, destination, filesystemError);
    if (filesystemError) {
        std::filesystem::remove(temporary, filesystemError);
        return fail(ErrorCode::io, "Unable to publish GLB atomically", filesystemError.message());
    }
    return GltfExportReport{
        asset.primitives.size(), instances.size(),      totalVertices,       totalIndices / 3,
        asset.materials.size(),  asset.textures.size(), asset.images.size(), totalBytes};
}

} // namespace aether::mesh
