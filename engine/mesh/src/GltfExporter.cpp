#include <aether/mesh/GltfExporter.hpp>
#include <aether/scene/Transform.hpp>

#include <fastgltf/core.hpp>
#include <fastgltf/types.hpp>

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <fstream>
#include <limits>
#include <memory>
#include <optional>
#include <ranges>
#include <string>
#include <string_view>

namespace aether::mesh {
namespace {

constexpr std::size_t glbMaximumBytes = std::numeric_limits<std::uint32_t>::max();

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

Result<void> checkName(std::string_view name, const GltfExportLimits& limits,
                       std::size_t& totalNameBytes, const char* kind) {
    if (name.size() > limits.maximumNameBytes)
        return fail(ErrorCode::resourceExhausted, std::string("GLB ") + kind + " name is too long");
    if (name.find('\0') != std::string_view::npos)
        return fail(ErrorCode::corruptData, std::string("GLB ") + kind + " name contains NUL");
    if (name.size() > limits.maximumTotalNameBytes - totalNameBytes)
        return fail(ErrorCode::resourceExhausted, "Static GLB names exceed their total byte limit");
    totalNameBytes += name.size();
    return {};
}

Result<fastgltf::MimeType> imageMime(std::span<const std::byte> bytes) {
    constexpr std::array png{std::byte{0x89}, std::byte{'P'},  std::byte{'N'},  std::byte{'G'},
                             std::byte{0x0d}, std::byte{0x0a}, std::byte{0x1a}, std::byte{0x0a}};
    if (bytes.size() >= png.size() && std::ranges::equal(png, bytes.first(png.size())))
        return fastgltf::MimeType::PNG;
    if (bytes.size() >= 3 && bytes[0] == std::byte{0xff} && bytes[1] == std::byte{0xd8} &&
        bytes[2] == std::byte{0xff})
        return fastgltf::MimeType::JPEG;
    return fail(ErrorCode::unsupported,
                "Static GLB export currently embeds only PNG or JPEG texture images");
}

fastgltf::Filter minificationFilter(const TextureAsset& texture) {
    if (texture.mipFilter == SamplerMipFilter::none)
        return texture.minification == SamplerFilter::nearest ? fastgltf::Filter::Nearest
                                                              : fastgltf::Filter::Linear;
    if (texture.mipFilter == SamplerMipFilter::nearest)
        return texture.minification == SamplerFilter::nearest
                   ? fastgltf::Filter::NearestMipMapNearest
                   : fastgltf::Filter::LinearMipMapNearest;
    return texture.minification == SamplerFilter::nearest ? fastgltf::Filter::NearestMipMapLinear
                                                          : fastgltf::Filter::LinearMipMapLinear;
}

fastgltf::Wrap wrapMode(SamplerAddressMode mode) {
    switch (mode) {
    case SamplerAddressMode::clampToEdge:
        return fastgltf::Wrap::ClampToEdge;
    case SamplerAddressMode::mirroredRepeat:
        return fastgltf::Wrap::MirroredRepeat;
    case SamplerAddressMode::repeat:
        return fastgltf::Wrap::Repeat;
    }
    return fastgltf::Wrap::Repeat;
}

bool defaultTransform(const PbrMaterial::UvTransform& transform) {
    return transform.scale.x == 1.0F && transform.scale.y == 1.0F && transform.offset.x == 0.0F &&
           transform.offset.y == 0.0F && transform.rotation == 0.0F;
}

template <typename TextureInfo>
Result<TextureInfo> makeTextureInfo(std::size_t textureIndex,
                                    const PbrMaterial::UvTransform& transform,
                                    std::size_t textureCount) {
    if (textureIndex >= textureCount)
        return fail(ErrorCode::corruptData, "GLB material references an invalid texture");
    if (!finite(transform.scale) || !finite(transform.offset) || !std::isfinite(transform.rotation))
        return fail(ErrorCode::corruptData, "GLB material UV transform is not finite");
    TextureInfo info;
    info.textureIndex = textureIndex;
    info.texCoordIndex = 0;
    if (!defaultTransform(transform)) {
        info.transform = std::make_unique<fastgltf::TextureTransform>();
        info.transform->rotation = transform.rotation;
        info.transform->uvOffset = {transform.offset.x, transform.offset.y};
        info.transform->uvScale = {transform.scale.x, transform.scale.y};
    }
    return info;
}

bool hasTextureTransform(const PbrMaterial& material) {
    const std::array bindings{material.baseColorTexture, material.metallicRoughnessTexture,
                              material.normalTexture, material.occlusionTexture,
                              material.emissiveTexture};
    for (std::size_t index = 0; index < bindings.size(); ++index)
        if (bindings[index] && !defaultTransform(material.uvTransforms[index]))
            return true;
    return false;
}

bool isImplicitDefault(const PbrMaterial& material) {
    return material.baseColor.x == 1.0F && material.baseColor.y == 1.0F &&
           material.baseColor.z == 1.0F && material.baseColor.w == 1.0F &&
           material.emissive.x == 0.0F && material.emissive.y == 0.0F &&
           material.emissive.z == 0.0F && material.metallic == 1.0F && material.roughness == 1.0F &&
           material.normalScale == 1.0F && material.occlusionStrength == 1.0F &&
           material.alphaCutoff == 0.5F && !material.doubleSided && !material.alphaBlend &&
           !material.alphaMask && !material.baseColorTexture &&
           !material.metallicRoughnessTexture && !material.normalTexture &&
           !material.occlusionTexture && !material.emissiveTexture;
}

class StaticAssetBuilder final {
  public:
    explicit StaticAssetBuilder(const GltfExportLimits& limits) : limits_(limits) {}

    Result<fastgltf::Asset> build(const MeshAsset& source) {
        if (source.primitives.empty())
            return fail(ErrorCode::invalidArgument, "Cannot export a GLB with no primitives");
        if (source.primitives.size() > limits_.maximumPrimitives ||
            source.materials.size() > limits_.maximumMaterials ||
            source.textures.size() > limits_.maximumTextures ||
            source.images.size() > limits_.maximumImages)
            return fail(ErrorCode::resourceExhausted,
                        "Static GLB asset exceeds object-count limits");
        if (!source.animations.empty() || !source.skins.empty())
            return fail(ErrorCode::unsupported,
                        "Static GLB export does not accept animations or skins");
        if (auto name = checkName(source.name, limits_, totalNameBytes_, "asset"); !name)
            return std::unexpected(name.error());

        fastgltf::Asset output;
        fastgltf::AssetInfo info;
        info.gltfVersion = "2.0";
        info.generator = "Maveb deterministic native static GLB exporter";
        output.assetInfo = std::move(info);

        if (auto images = appendImages(source, output); !images)
            return std::unexpected(images.error());
        if (auto textures = appendTextures(source, output); !textures)
            return std::unexpected(textures.error());
        if (auto materials = appendMaterials(source, output); !materials)
            return std::unexpected(materials.error());
        if (auto meshes = appendMeshes(source, output); !meshes)
            return std::unexpected(meshes.error());
        if (auto scene = appendScene(source, output); !scene)
            return std::unexpected(scene.error());

        fastgltf::Buffer buffer;
        buffer.byteLength = binary_.size();
        buffer.name = "Maveb canonical binary payload";
        buffer.data = fastgltf::sources::Vector{std::move(binary_), fastgltf::MimeType::GltfBuffer};
        output.buffers.push_back(std::move(buffer));
        return output;
    }

  private:
    Result<void> ensureGrowth(std::size_t bytes) const {
        const auto maximum = std::min<std::uint64_t>(limits_.maximumOutputBytes, glbMaximumBytes);
        if (bytes > maximum || binary_.size() > maximum - bytes)
            return fail(ErrorCode::resourceExhausted,
                        "Static GLB binary payload exceeds its limit");
        return {};
    }

    Result<void> alignBinary() {
        const std::size_t padding = (4U - binary_.size() % 4U) % 4U;
        if (auto growth = ensureGrowth(padding); !growth)
            return growth;
        binary_.insert(binary_.end(), padding, std::byte{0});
        return {};
    }

    Result<std::size_t> beginView() {
        if (auto aligned = alignBinary(); !aligned)
            return std::unexpected(aligned.error());
        return binary_.size();
    }

    Result<void> append32(std::uint32_t value) {
        if (auto growth = ensureGrowth(sizeof(value)); !growth)
            return growth;
        for (std::uint32_t shift = 0; shift < 32; shift += 8)
            binary_.push_back(static_cast<std::byte>((value >> shift) & 0xffU));
        return {};
    }

    Result<void> appendFloat(float value) {
        return append32(std::bit_cast<std::uint32_t>(value));
    }

    Result<std::size_t> finishView(fastgltf::Asset& output, std::size_t offset,
                                   std::optional<fastgltf::BufferTarget> target,
                                   std::string_view name) {
        if (binary_.size() <= offset)
            return fail(ErrorCode::corruptData, "Static GLB buffer view is empty");
        fastgltf::BufferView view;
        view.bufferIndex = 0;
        view.byteOffset = offset;
        view.byteLength = binary_.size() - offset;
        if (target)
            view.target = *target;
        view.name = std::string(name);
        output.bufferViews.push_back(std::move(view));
        return output.bufferViews.size() - 1;
    }

    Result<void> appendImages(const MeshAsset& source, fastgltf::Asset& output) {
        std::size_t totalImageBytes = 0;
        output.images.reserve(source.images.size());
        for (const auto& image : source.images) {
            if (auto name = checkName(image.name, limits_, totalNameBytes_, "image"); !name)
                return name;
            if (image.bytes.empty() || image.bytes.size() > limits_.maximumImageBytes ||
                totalImageBytes > limits_.maximumImageBytes - image.bytes.size())
                return fail(ErrorCode::resourceExhausted,
                            "Static GLB image bytes exceed their limit");
            auto mime = imageMime(image.bytes);
            if (!mime)
                return std::unexpected(mime.error());
            auto offset = beginView();
            if (!offset)
                return std::unexpected(offset.error());
            if (auto growth = ensureGrowth(image.bytes.size()); !growth)
                return growth;
            binary_.insert(binary_.end(), image.bytes.begin(), image.bytes.end());
            auto view = finishView(output, *offset, std::nullopt, image.name);
            if (!view)
                return std::unexpected(view.error());
            fastgltf::Image encoded;
            encoded.name = image.name;
            encoded.data = fastgltf::sources::BufferView{*view, *mime};
            output.images.push_back(std::move(encoded));
            totalImageBytes += image.bytes.size();
        }
        return {};
    }

    Result<void> appendTextures(const MeshAsset& source, fastgltf::Asset& output) const {
        output.samplers.reserve(source.textures.size());
        output.textures.reserve(source.textures.size());
        for (std::size_t index = 0; index < source.textures.size(); ++index) {
            const auto& texture = source.textures[index];
            if (texture.imageIndex >= source.images.size())
                return fail(ErrorCode::corruptData,
                            "Static GLB texture references an invalid image");
            fastgltf::Sampler sampler;
            sampler.name = "Sampler " + std::to_string(index);
            sampler.magFilter = texture.magnification == SamplerFilter::nearest
                                    ? fastgltf::Filter::Nearest
                                    : fastgltf::Filter::Linear;
            sampler.minFilter = minificationFilter(texture);
            sampler.wrapS = wrapMode(texture.addressU);
            sampler.wrapT = wrapMode(texture.addressV);
            output.samplers.push_back(std::move(sampler));

            fastgltf::Texture exported;
            exported.name = "Texture " + std::to_string(index);
            exported.imageIndex = texture.imageIndex;
            exported.samplerIndex = index;
            output.textures.push_back(std::move(exported));
        }
        return {};
    }

    Result<void> appendMaterials(const MeshAsset& source, fastgltf::Asset& output) {
        if (!source.materials.empty() && !isImplicitDefault(source.materials.front()))
            return fail(ErrorCode::corruptData,
                        "Static GLB material slot zero must remain the implicit default");
        if (std::ranges::any_of(source.materials, hasTextureTransform))
            output.extensionsUsed.emplace_back(fastgltf::extensions::KHR_texture_transform);
        if (source.materials.size() > 1)
            output.materials.reserve(source.materials.size() - 1);
        for (std::size_t index = 1; index < source.materials.size(); ++index) {
            const auto& material = source.materials[index];
            if (auto name = checkName(material.name, limits_, totalNameBytes_, "material"); !name)
                return name;
            if (!finite(material.baseColor) || !finite(material.emissive) ||
                !std::isfinite(material.metallic) || !std::isfinite(material.roughness) ||
                !std::isfinite(material.normalScale) ||
                !std::isfinite(material.occlusionStrength) ||
                !std::isfinite(material.alphaCutoff) || material.metallic < 0.0F ||
                material.metallic > 1.0F || material.roughness < 0.0F ||
                material.roughness > 1.0F || material.normalScale < 0.0F ||
                material.occlusionStrength < 0.0F || material.occlusionStrength > 1.0F ||
                material.alphaCutoff < 0.0F || material.alphaCutoff > 1.0F ||
                std::ranges::any_of(std::array{material.baseColor.x, material.baseColor.y,
                                               material.baseColor.z, material.baseColor.w},
                                    [](float value) { return value < 0.0F || value > 1.0F; }) ||
                material.emissive.x < 0.0F || material.emissive.y < 0.0F ||
                material.emissive.z < 0.0F)
                return fail(ErrorCode::corruptData, "Static GLB material factors are invalid");
            if (material.alphaBlend && material.alphaMask)
                return fail(ErrorCode::corruptData,
                            "Static GLB material cannot be alpha blend and alpha mask");

            fastgltf::Material exported;
            exported.name = material.name;
            exported.pbrData.baseColorFactor = {material.baseColor.x, material.baseColor.y,
                                                material.baseColor.z, material.baseColor.w};
            exported.pbrData.metallicFactor = material.metallic;
            exported.pbrData.roughnessFactor = material.roughness;
            exported.emissiveFactor = {material.emissive.x, material.emissive.y,
                                       material.emissive.z};
            exported.doubleSided = material.doubleSided;
            exported.alphaCutoff = material.alphaCutoff;
            exported.alphaMode = material.alphaBlend  ? fastgltf::AlphaMode::Blend
                                 : material.alphaMask ? fastgltf::AlphaMode::Mask
                                                      : fastgltf::AlphaMode::Opaque;
            if (material.baseColorTexture) {
                auto info = makeTextureInfo<fastgltf::TextureInfo>(
                    *material.baseColorTexture, material.uvTransforms[0], source.textures.size());
                if (!info)
                    return std::unexpected(info.error());
                exported.pbrData.baseColorTexture = std::move(*info);
            }
            if (material.metallicRoughnessTexture) {
                auto info = makeTextureInfo<fastgltf::TextureInfo>(
                    *material.metallicRoughnessTexture, material.uvTransforms[1],
                    source.textures.size());
                if (!info)
                    return std::unexpected(info.error());
                exported.pbrData.metallicRoughnessTexture = std::move(*info);
            }
            if (material.normalTexture) {
                auto info = makeTextureInfo<fastgltf::NormalTextureInfo>(
                    *material.normalTexture, material.uvTransforms[2], source.textures.size());
                if (!info)
                    return std::unexpected(info.error());
                info->scale = material.normalScale;
                exported.normalTexture = std::move(*info);
            }
            if (material.occlusionTexture) {
                auto info = makeTextureInfo<fastgltf::OcclusionTextureInfo>(
                    *material.occlusionTexture, material.uvTransforms[3], source.textures.size());
                if (!info)
                    return std::unexpected(info.error());
                info->strength = material.occlusionStrength;
                exported.occlusionTexture = std::move(*info);
            }
            if (material.emissiveTexture) {
                auto info = makeTextureInfo<fastgltf::TextureInfo>(
                    *material.emissiveTexture, material.uvTransforms[4], source.textures.size());
                if (!info)
                    return std::unexpected(info.error());
                exported.emissiveTexture = std::move(*info);
            }
            output.materials.push_back(std::move(exported));
        }
        return {};
    }

    // The adjacent indices deliberately mirror glTF's buffer-view then element-count fields.
    // NOLINTNEXTLINE(bugprone-easily-swappable-parameters)
    Result<std::size_t> appendAccessor(fastgltf::Asset& output, std::size_t view, std::size_t count,
                                       fastgltf::AccessorType type,
                                       fastgltf::ComponentType component, std::string_view name) {
        fastgltf::Accessor accessor;
        accessor.bufferViewIndex = view;
        accessor.byteOffset = 0;
        accessor.count = count;
        accessor.type = type;
        accessor.componentType = component;
        accessor.name = std::string(name);
        output.accessors.push_back(std::move(accessor));
        return output.accessors.size() - 1;
    }

    Result<void> appendMeshes(const MeshAsset& source, fastgltf::Asset& output) {
        std::size_t totalVertices = 0;
        std::size_t totalIndices = 0;
        output.meshes.reserve(source.primitives.size());
        for (std::size_t primitiveIndex = 0; primitiveIndex < source.primitives.size();
             ++primitiveIndex) {
            const auto& primitive = source.primitives[primitiveIndex];
            if (auto name = checkName(primitive.name, limits_, totalNameBytes_, "primitive"); !name)
                return name;
            if (primitive.vertices.empty() || primitive.indices.empty() ||
                primitive.indices.size() % 3 != 0)
                return fail(ErrorCode::corruptData,
                            "Static GLB primitive must contain indexed triangles");
            if (primitive.vertices.size() > limits_.maximumVertices - totalVertices ||
                primitive.indices.size() > limits_.maximumIndices - totalIndices)
                return fail(ErrorCode::resourceExhausted,
                            "Static GLB geometry exceeds vertex or index limits");
            if (primitive.hasSkinAttributes || !primitive.morphTargets.empty() ||
                !primitive.defaultMorphWeights.empty())
                return fail(ErrorCode::unsupported,
                            "Static GLB export does not accept skin or morph attributes");
            if (!primitive.vertexColors.empty() &&
                primitive.vertexColors.size() != primitive.vertices.size())
                return fail(ErrorCode::corruptData,
                            "Static GLB vertex-color count does not match vertices");
            if ((!source.materials.empty() && primitive.materialIndex >= source.materials.size()) ||
                (source.materials.empty() && primitive.materialIndex != 0))
                return fail(ErrorCode::corruptData,
                            "Static GLB primitive references an invalid material");

            simd_float3 minimum = primitive.vertices.front().position;
            simd_float3 maximum = minimum;
            bool hasAnyTangent = false;
            bool hasCompleteTangents = true;
            for (const auto& vertex : primitive.vertices) {
                if (!finite(vertex.position) || !finite(vertex.normal) || !finite(vertex.tangent) ||
                    !finite(vertex.textureCoordinate) ||
                    std::abs(simd_length(vertex.normal) - 1.0F) > 1.0e-3F)
                    return fail(ErrorCode::corruptData,
                                "Static GLB primitive contains invalid vertex attributes");
                const simd_float3 tangent = {vertex.tangent.x, vertex.tangent.y, vertex.tangent.z};
                const bool tangentPresent = simd_length_squared(tangent) > 1.0e-20F;
                hasAnyTangent = hasAnyTangent || tangentPresent;
                hasCompleteTangents = hasCompleteTangents && tangentPresent &&
                                      std::abs(simd_length(tangent) - 1.0F) <= 1.0e-3F &&
                                      std::abs(std::abs(vertex.tangent.w) - 1.0F) <= 1.0e-6F;
                minimum = simd_min(minimum, vertex.position);
                maximum = simd_max(maximum, vertex.position);
            }
            if (hasAnyTangent && !hasCompleteTangents)
                return fail(ErrorCode::corruptData,
                            "Static GLB primitive contains partial or invalid tangents");
            for (const auto color : primitive.vertexColors)
                if (!finite(color) || color.x < 0.0F || color.x > 1.0F || color.y < 0.0F ||
                    color.y > 1.0F || color.z < 0.0F || color.z > 1.0F)
                    return fail(ErrorCode::corruptData,
                                "Static GLB primitive contains an invalid vertex color");
            for (std::size_t index = 0; index < primitive.indices.size(); index += 3) {
                const auto a = primitive.indices[index];
                const auto b = primitive.indices[index + 1];
                const auto c = primitive.indices[index + 2];
                if (a >= primitive.vertices.size() || b >= primitive.vertices.size() ||
                    c >= primitive.vertices.size() || a == b || b == c || a == c)
                    return fail(ErrorCode::corruptData,
                                "Static GLB primitive contains an invalid triangle");
                const auto edge1 = primitive.vertices[b].position - primitive.vertices[a].position;
                const auto edge2 = primitive.vertices[c].position - primitive.vertices[a].position;
                if (simd_length_squared(simd_cross(edge1, edge2)) <= 1.0e-20F)
                    return fail(ErrorCode::corruptData,
                                "Static GLB primitive contains a zero-area triangle");
            }

            fastgltf::Primitive exportedPrimitive;
            auto position = appendVec3(output, primitive, &MeshVertex::position, "POSITION");
            auto normal = appendVec3(output, primitive, &MeshVertex::normal, "NORMAL");
            auto uv = appendVec2(output, primitive, &MeshVertex::textureCoordinate, "TEXCOORD_0");
            auto indices = appendIndices(output, primitive);
            if (!position || !normal || !uv || !indices)
                return std::unexpected((!position ? position.error()
                                        : !normal ? normal.error()
                                        : !uv     ? uv.error()
                                                  : indices.error()));
            output.accessors[*position].min = fastgltf::AccessorBoundsArray::ForType<double>(3);
            output.accessors[*position].max = fastgltf::AccessorBoundsArray::ForType<double>(3);
            for (std::size_t axis = 0; axis < 3; ++axis) {
                output.accessors[*position].min->set<double>(axis, minimum[axis]);
                output.accessors[*position].max->set<double>(axis, maximum[axis]);
            }
            exportedPrimitive.attributes.emplace_back(fastgltf::Attribute{"POSITION", *position});
            exportedPrimitive.attributes.emplace_back(fastgltf::Attribute{"NORMAL", *normal});
            if (hasCompleteTangents) {
                auto tangent = appendVec4(output, primitive, &MeshVertex::tangent, "TANGENT");
                if (!tangent)
                    return std::unexpected(tangent.error());
                exportedPrimitive.attributes.emplace_back(fastgltf::Attribute{"TANGENT", *tangent});
            }
            exportedPrimitive.attributes.emplace_back(fastgltf::Attribute{"TEXCOORD_0", *uv});
            if (!primitive.vertexColors.empty()) {
                auto color = appendColors(output, primitive);
                if (!color)
                    return std::unexpected(color.error());
                exportedPrimitive.attributes.emplace_back(fastgltf::Attribute{"COLOR_0", *color});
            }
            exportedPrimitive.indicesAccessor = *indices;
            if (primitive.materialIndex > 0)
                exportedPrimitive.materialIndex = primitive.materialIndex - 1;

            fastgltf::Mesh mesh;
            mesh.name = primitive.name.empty() ? "Primitive " + std::to_string(primitiveIndex)
                                               : primitive.name;
            mesh.primitives.push_back(std::move(exportedPrimitive));
            output.meshes.push_back(std::move(mesh));
            totalVertices += primitive.vertices.size();
            totalIndices += primitive.indices.size();
        }
        return {};
    }

    template <typename Member>
    Result<std::size_t> appendAttribute(fastgltf::Asset& output, const MeshPrimitive& primitive,
                                        Member member, std::size_t components,
                                        fastgltf::AccessorType type, std::string_view name) {
        auto offset = beginView();
        if (!offset)
            return std::unexpected(offset.error());
        for (const auto& vertex : primitive.vertices)
            for (std::size_t component = 0; component < components; ++component)
                if (auto appended = appendFloat((vertex.*member)[component]); !appended)
                    return std::unexpected(appended.error());
        auto view = finishView(output, *offset, fastgltf::BufferTarget::ArrayBuffer, name);
        if (!view)
            return std::unexpected(view.error());
        return appendAccessor(output, *view, primitive.vertices.size(), type,
                              fastgltf::ComponentType::Float, name);
    }

    Result<std::size_t> appendVec2(fastgltf::Asset& output, const MeshPrimitive& primitive,
                                   simd_float2 MeshVertex::*member, std::string_view name) {
        return appendAttribute(output, primitive, member, 2, fastgltf::AccessorType::Vec2, name);
    }

    Result<std::size_t> appendVec3(fastgltf::Asset& output, const MeshPrimitive& primitive,
                                   simd_float3 MeshVertex::*member, std::string_view name) {
        return appendAttribute(output, primitive, member, 3, fastgltf::AccessorType::Vec3, name);
    }

    Result<std::size_t> appendVec4(fastgltf::Asset& output, const MeshPrimitive& primitive,
                                   simd_float4 MeshVertex::*member, std::string_view name) {
        return appendAttribute(output, primitive, member, 4, fastgltf::AccessorType::Vec4, name);
    }

    Result<std::size_t> appendColors(fastgltf::Asset& output, const MeshPrimitive& primitive) {
        auto offset = beginView();
        if (!offset)
            return std::unexpected(offset.error());
        for (const auto color : primitive.vertexColors)
            for (std::size_t component = 0; component < 3; ++component)
                if (auto appended = appendFloat(color[component]); !appended)
                    return std::unexpected(appended.error());
        auto view = finishView(output, *offset, fastgltf::BufferTarget::ArrayBuffer, "COLOR_0");
        if (!view)
            return std::unexpected(view.error());
        return appendAccessor(output, *view, primitive.vertexColors.size(),
                              fastgltf::AccessorType::Vec3, fastgltf::ComponentType::Float,
                              "COLOR_0");
    }

    Result<std::size_t> appendIndices(fastgltf::Asset& output, const MeshPrimitive& primitive) {
        auto offset = beginView();
        if (!offset)
            return std::unexpected(offset.error());
        for (const auto index : primitive.indices)
            if (auto appended = append32(index); !appended)
                return std::unexpected(appended.error());
        auto view =
            finishView(output, *offset, fastgltf::BufferTarget::ElementArrayBuffer, "INDICES");
        if (!view)
            return std::unexpected(view.error());
        return appendAccessor(output, *view, primitive.indices.size(),
                              fastgltf::AccessorType::Scalar, fastgltf::ComponentType::UnsignedInt,
                              "INDICES");
    }

    Result<void> appendScene(const MeshAsset& source, fastgltf::Asset& output) {
        std::vector<MeshInstance> instances = source.instances;
        if (instances.empty()) {
            instances.reserve(source.primitives.size());
            for (std::size_t index = 0; index < source.primitives.size(); ++index) {
                MeshInstance instance;
                instance.name = source.primitives[index].name;
                instance.primitiveIndex = index;
                instances.push_back(std::move(instance));
            }
        }
        if (instances.size() > limits_.maximumInstances)
            return fail(ErrorCode::resourceExhausted, "Static GLB exceeds instance-count limit");
        fastgltf::Scene exportedScene;
        exportedScene.name = source.name.empty() ? "Maveb Scene" : source.name;
        exportedScene.nodeIndices.reserve(instances.size());
        output.nodes.reserve(instances.size());
        for (std::size_t index = 0; index < instances.size(); ++index) {
            const auto& instance = instances[index];
            if (instance.primitiveIndex >= source.primitives.size())
                return fail(ErrorCode::corruptData,
                            "Static GLB instance references an invalid primitive");
            if (instance.skinIndex || !instance.morphWeights.empty())
                return fail(ErrorCode::unsupported,
                            "Static GLB export does not accept skinned or morphed instances");
            if (!finite(instance.worldTransform) ||
                std::abs(simd_determinant(instance.worldTransform)) < 1.0e-8F ||
                std::abs(instance.worldTransform.columns[0].w) > 1.0e-6F ||
                std::abs(instance.worldTransform.columns[1].w) > 1.0e-6F ||
                std::abs(instance.worldTransform.columns[2].w) > 1.0e-6F ||
                std::abs(instance.worldTransform.columns[3].w - 1.0F) > 1.0e-6F)
                return fail(ErrorCode::corruptData,
                            "Static GLB instance transform is non-finite or singular");
            if (auto name = checkName(instance.name, limits_, totalNameBytes_, "instance"); !name)
                return name;
            auto decomposed = ::aether::scene::decomposeTransform(instance.worldTransform);
            if (!decomposed)
                return fail(ErrorCode::unsupported,
                            "Static GLB instance transform cannot be represented as TRS",
                            decomposed.error().describe());
            fastgltf::TRS transform;
            transform.translation = fastgltf::math::fvec3{
                decomposed->translation.x, decomposed->translation.y, decomposed->translation.z};
            transform.rotation =
                fastgltf::math::fquat{decomposed->rotation.vector.x, decomposed->rotation.vector.y,
                                      decomposed->rotation.vector.z, decomposed->rotation.vector.w};
            transform.scale = fastgltf::math::fvec3{decomposed->scale.x, decomposed->scale.y,
                                                    decomposed->scale.z};
            fastgltf::Node node;
            node.name = instance.name.empty() ? "Instance " + std::to_string(index) : instance.name;
            node.meshIndex = instance.primitiveIndex;
            node.transform = transform;
            output.nodes.push_back(std::move(node));
            exportedScene.nodeIndices.push_back(index);
        }
        output.scenes.push_back(std::move(exportedScene));
        output.defaultScene = 0;
        return {};
    }

    const GltfExportLimits& limits_;
    std::size_t totalNameBytes_{};
    std::vector<std::byte> binary_;
};

} // namespace

Result<std::vector<std::byte>> GltfExporter::encodeStatic(const MeshAsset& asset,
                                                          const GltfExportLimits& limits) {
    if (limits.maximumOutputBytes == 0 || limits.maximumOutputBytes > glbMaximumBytes ||
        limits.maximumPrimitives == 0 || limits.maximumInstances == 0 ||
        limits.maximumMaterials == 0 || limits.maximumTextures == 0 ||
        limits.maximumVertices == 0 || limits.maximumIndices == 0 || limits.maximumImages == 0 ||
        limits.maximumImageBytes == 0 || limits.maximumNameBytes == 0 ||
        limits.maximumTotalNameBytes == 0)
        return fail(ErrorCode::invalidArgument, "Static GLB export limits are invalid");
    StaticAssetBuilder builder(limits);
    auto output = builder.build(asset);
    if (!output)
        return std::unexpected(output.error());
    fastgltf::Exporter exporter;
    auto encoded = exporter.writeGltfBinary(*output, fastgltf::ExportOptions::ValidateAsset);
    if (!encoded)
        return fail(ErrorCode::corruptData, "fastgltf rejected the authored static GLB asset",
                    std::string(fastgltf::getErrorMessage(encoded.error())));
    if (encoded->output.empty() || encoded->output.size() > limits.maximumOutputBytes)
        return fail(ErrorCode::resourceExhausted, "Encoded static GLB exceeds its output limit");
    if (std::ranges::any_of(encoded->bufferPaths,
                            [](const auto& path) { return path.has_value(); }) ||
        std::ranges::any_of(encoded->imagePaths, [](const auto& path) { return path.has_value(); }))
        return fail(ErrorCode::internal, "Static GLB exporter left an external resource");
    return std::move(encoded->output);
}

Result<void> GltfExporter::writeStatic(const MeshAsset& asset,
                                       const std::filesystem::path& destination,
                                       const GltfExportLimits& limits) {
    if (destination.empty() || destination.extension() != ".glb")
        return fail(ErrorCode::invalidArgument, "Static GLB output must use the .glb extension");
    auto encoded = encodeStatic(asset, limits);
    if (!encoded)
        return std::unexpected(encoded.error());
    auto temporary = destination;
    temporary += ".tmp";
    std::error_code filesystemError;
    std::filesystem::remove(temporary, filesystemError);
    std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
    if (!stream)
        return fail(ErrorCode::io, "Unable to create temporary GLB", temporary.string());
    stream.write(reinterpret_cast<const char*>(encoded->data()),
                 static_cast<std::streamsize>(encoded->size()));
    stream.flush();
    if (!stream.good()) {
        stream.close();
        std::filesystem::remove(temporary, filesystemError);
        return fail(ErrorCode::io, "Unable to write complete GLB", destination.string());
    }
    stream.close();
    std::filesystem::rename(temporary, destination, filesystemError);
    if (filesystemError) {
        std::filesystem::remove(temporary, filesystemError);
        return fail(ErrorCode::io, "Unable to publish GLB atomically", destination.string());
    }
    return {};
}

} // namespace aether::mesh
