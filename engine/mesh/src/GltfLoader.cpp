#include <aether/mesh/GltfLoader.hpp>

#include <fastgltf/core.hpp>
#include <fastgltf/tools.hpp>

#include <algorithm>
#include <cmath>
#include <limits>

namespace aether::mesh {
namespace {

Result<void> checkGrowth(std::size_t current, std::size_t additional, std::size_t limit,
                         const char* kind) {
    if (additional > limit || current > limit - additional) {
        return fail(ErrorCode::resourceExhausted, std::string("glTF exceeds ") + kind + " limit");
    }
    return {};
}

simd_float4x4 toSimd(const fastgltf::math::fmat4x4& source) {
    simd_float4x4 result{};
    for (std::size_t column = 0; column < 4; ++column)
        for (std::size_t row = 0; row < 4; ++row)
            result.columns[column][row] = source[column][row];
    return result;
}

void generateNormals(MeshPrimitive& primitive) {
    for (auto& vertex : primitive.vertices) {
        vertex.normal = {0.0F, 0.0F, 0.0F};
    }
    for (std::size_t index = 0; index + 2 < primitive.indices.size(); index += 3) {
        const std::uint32_t i0 = primitive.indices[index];
        const std::uint32_t i1 = primitive.indices[index + 1];
        const std::uint32_t i2 = primitive.indices[index + 2];
        if (i0 >= primitive.vertices.size() || i1 >= primitive.vertices.size() ||
            i2 >= primitive.vertices.size()) {
            continue;
        }
        const simd_float3 edge1 = primitive.vertices[i1].position - primitive.vertices[i0].position;
        const simd_float3 edge2 = primitive.vertices[i2].position - primitive.vertices[i0].position;
        const simd_float3 normal = simd_cross(edge1, edge2);
        primitive.vertices[i0].normal += normal;
        primitive.vertices[i1].normal += normal;
        primitive.vertices[i2].normal += normal;
    }
    for (auto& vertex : primitive.vertices) {
        const float lengthSquared = simd_length_squared(vertex.normal);
        vertex.normal = lengthSquared > 1.0e-12F ? simd_normalize(vertex.normal)
                                                 : simd_float3{0.0F, 1.0F, 0.0F};
    }
}

void generateTangents(MeshPrimitive& primitive) {
    std::vector<simd_float3> tangents(primitive.vertices.size());
    std::vector<simd_float3> bitangents(primitive.vertices.size());
    for (std::size_t index = 0; index + 2 < primitive.indices.size(); index += 3) {
        const std::uint32_t indices[3]{primitive.indices[index], primitive.indices[index + 1],
                                       primitive.indices[index + 2]};
        const auto& v0 = primitive.vertices[indices[0]];
        const auto& v1 = primitive.vertices[indices[1]];
        const auto& v2 = primitive.vertices[indices[2]];
        const simd_float3 edge1 = v1.position - v0.position;
        const simd_float3 edge2 = v2.position - v0.position;
        const simd_float2 uv1 = v1.textureCoordinate - v0.textureCoordinate;
        const simd_float2 uv2 = v2.textureCoordinate - v0.textureCoordinate;
        const float determinant = uv1.x * uv2.y - uv1.y * uv2.x;
        if (std::abs(determinant) <= 1.0e-12F)
            continue;
        const float inverse = 1.0F / determinant;
        const simd_float3 tangent = (edge1 * uv2.y - edge2 * uv1.y) * inverse;
        const simd_float3 bitangent = (edge2 * uv1.x - edge1 * uv2.x) * inverse;
        for (const std::uint32_t vertex : indices) {
            tangents[vertex] += tangent;
            bitangents[vertex] += bitangent;
        }
    }
    for (std::size_t index = 0; index < primitive.vertices.size(); ++index) {
        const simd_float3 normal = primitive.vertices[index].normal;
        simd_float3 tangent = tangents[index] - normal * simd_dot(normal, tangents[index]);
        if (simd_length_squared(tangent) <= 1.0e-12F) {
            const simd_float3 axis = std::abs(normal.y) < 0.999F ? simd_float3{0.0F, 1.0F, 0.0F}
                                                                 : simd_float3{1.0F, 0.0F, 0.0F};
            tangent = simd_normalize(simd_cross(axis, normal));
        } else {
            tangent = simd_normalize(tangent);
        }
        const float handedness =
            simd_dot(simd_cross(normal, tangent), bitangents[index]) < 0.0F ? -1.0F : 1.0F;
        primitive.vertices[index].tangent = {tangent.x, tangent.y, tangent.z, handedness};
    }
}

Result<std::vector<std::byte>> copyImageBytes(const fastgltf::Asset& asset,
                                              const fastgltf::Image& image) {
    fastgltf::span<const std::byte> bytes;
    if (const auto* arraySource = std::get_if<fastgltf::sources::Array>(&image.data)) {
        bytes =
            fastgltf::span<const std::byte>(arraySource->bytes.data(), arraySource->bytes.size());
    } else if (const auto* vectorSource = std::get_if<fastgltf::sources::Vector>(&image.data)) {
        bytes =
            fastgltf::span<const std::byte>(vectorSource->bytes.data(), vectorSource->bytes.size());
    } else if (const auto* byteViewSource = std::get_if<fastgltf::sources::ByteView>(&image.data)) {
        bytes = byteViewSource->bytes;
    } else if (const auto* bufferViewSource =
                   std::get_if<fastgltf::sources::BufferView>(&image.data)) {
        bytes = fastgltf::DefaultBufferDataAdapter{}(asset, bufferViewSource->bufferViewIndex);
    } else {
        return fail(ErrorCode::unsupported, "glTF image source could not be loaded locally");
    }
    if (bytes.empty())
        return fail(ErrorCode::corruptData, "glTF image payload is empty");
    return std::vector<std::byte>(bytes.begin(), bytes.end());
}

SamplerAddressMode addressMode(fastgltf::Wrap wrap) {
    switch (wrap) {
    case fastgltf::Wrap::ClampToEdge:
        return SamplerAddressMode::clampToEdge;
    case fastgltf::Wrap::MirroredRepeat:
        return SamplerAddressMode::mirroredRepeat;
    case fastgltf::Wrap::Repeat:
        return SamplerAddressMode::repeat;
    }
    return SamplerAddressMode::repeat;
}

void applyMinificationFilter(TextureAsset& texture, fastgltf::Filter filter) {
    switch (filter) {
    case fastgltf::Filter::Nearest:
        texture.minification = SamplerFilter::nearest;
        texture.mipFilter = SamplerMipFilter::none;
        break;
    case fastgltf::Filter::Linear:
        texture.minification = SamplerFilter::linear;
        texture.mipFilter = SamplerMipFilter::none;
        break;
    case fastgltf::Filter::NearestMipMapNearest:
        texture.minification = SamplerFilter::nearest;
        texture.mipFilter = SamplerMipFilter::nearest;
        break;
    case fastgltf::Filter::LinearMipMapNearest:
        texture.minification = SamplerFilter::linear;
        texture.mipFilter = SamplerMipFilter::nearest;
        break;
    case fastgltf::Filter::NearestMipMapLinear:
        texture.minification = SamplerFilter::nearest;
        texture.mipFilter = SamplerMipFilter::linear;
        break;
    case fastgltf::Filter::LinearMipMapLinear:
        texture.minification = SamplerFilter::linear;
        texture.mipFilter = SamplerMipFilter::linear;
        break;
    }
}

} // namespace

std::size_t MeshAsset::vertexCount() const noexcept {
    std::size_t result = 0;
    for (const auto& primitive : primitives)
        result += primitive.vertices.size();
    return result;
}

std::size_t MeshAsset::indexCount() const noexcept {
    std::size_t result = 0;
    for (const auto& primitive : primitives)
        result += primitive.indices.size();
    return result;
}

Result<MeshAsset> loadData(fastgltf::GltfDataGetter& source, const std::filesystem::path& directory,
                           std::string_view diagnosticName, const GltfLimits& limits) {
    fastgltf::Parser parser(fastgltf::Extensions::KHR_mesh_quantization |
                            fastgltf::Extensions::KHR_texture_transform);
    constexpr auto options =
        fastgltf::Options::LoadExternalBuffers | fastgltf::Options::LoadExternalImages |
        fastgltf::Options::GenerateMeshIndices | fastgltf::Options::DecomposeNodeMatrices;
    auto parsed = parser.loadGltf(source, directory, options,
                                  fastgltf::Category::OnlyRenderable |
                                      fastgltf::Category::Animations | fastgltf::Category::Skins);
    if (parsed.error() != fastgltf::Error::None) {
        return fail(ErrorCode::corruptData, "glTF validation failed",
                    std::string(fastgltf::getErrorMessage(parsed.error())));
    }
    fastgltf::Asset& sourceAsset = parsed.get();

    MeshAsset result;
    result.name = std::string(diagnosticName);
    result.nodes.resize(sourceAsset.nodes.size());
    for (std::size_t nodeIndex = 0; nodeIndex < sourceAsset.nodes.size(); ++nodeIndex) {
        const auto& sourceNode = sourceAsset.nodes[nodeIndex];
        auto& node = result.nodes[nodeIndex];
        node.name = sourceNode.name.empty() ? "Node " + std::to_string(nodeIndex)
                                            : std::string(sourceNode.name);
        const auto* trs = std::get_if<fastgltf::TRS>(&sourceNode.transform);
        if (!trs)
            return fail(ErrorCode::corruptData, "glTF node matrix was not decomposed to TRS");
        node.localTransform.translation = {static_cast<float>(trs->translation[0]),
                                           static_cast<float>(trs->translation[1]),
                                           static_cast<float>(trs->translation[2])};
        node.localTransform.rotation = simd_quatf{simd_float4{
            static_cast<float>(trs->rotation[0]), static_cast<float>(trs->rotation[1]),
            static_cast<float>(trs->rotation[2]), static_cast<float>(trs->rotation[3])}};
        node.localTransform.scale = {static_cast<float>(trs->scale[0]),
                                     static_cast<float>(trs->scale[1]),
                                     static_cast<float>(trs->scale[2])};
        if (!scene::isFinite(node.localTransform) ||
            simd_length_squared(node.localTransform.rotation.vector) < 1.0e-12F ||
            !scene::hasNonZeroScale(node.localTransform))
            return fail(ErrorCode::corruptData, "glTF node contains invalid transform", node.name);
        node.localTransform.rotation = simd_normalize(node.localTransform.rotation);
        node.children.assign(sourceNode.children.begin(), sourceNode.children.end());
        for (const auto child : node.children) {
            if (child >= result.nodes.size())
                return fail(ErrorCode::corruptData, "glTF node child index is invalid", node.name);
            if (result.nodes[child].parentIndex)
                return fail(ErrorCode::corruptData, "glTF node has multiple parents", node.name);
            result.nodes[child].parentIndex = nodeIndex;
        }
    }
    if (sourceAsset.skins.size() > limits.maximumSkins)
        return fail(ErrorCode::resourceExhausted, "glTF exceeds skin-count limit");
    std::size_t totalJoints = 0;
    result.skins.reserve(sourceAsset.skins.size());
    for (const auto& sourceSkin : sourceAsset.skins) {
        if (sourceSkin.joints.empty() ||
            sourceSkin.joints.size() > limits.maximumJoints - totalJoints)
            return fail(ErrorCode::resourceExhausted, "glTF exceeds joint-count limit");
        totalJoints += sourceSkin.joints.size();
        MeshSkin skin;
        skin.name = sourceSkin.name.empty() ? "Skin " + std::to_string(result.skins.size())
                                            : std::string(sourceSkin.name);
        skin.jointNodeIndices.assign(sourceSkin.joints.begin(), sourceSkin.joints.end());
        if (std::ranges::any_of(skin.jointNodeIndices,
                                [&](std::size_t joint) { return joint >= result.nodes.size(); }))
            return fail(ErrorCode::corruptData, "glTF skin joint index is invalid", skin.name);
        skin.inverseBindMatrices.assign(skin.jointNodeIndices.size(), matrix_identity_float4x4);
        if (sourceSkin.inverseBindMatrices) {
            if (*sourceSkin.inverseBindMatrices >= sourceAsset.accessors.size())
                return fail(ErrorCode::corruptData, "glTF inverse-bind accessor is invalid",
                            skin.name);
            const auto& accessor = sourceAsset.accessors[*sourceSkin.inverseBindMatrices];
            if (accessor.type != fastgltf::AccessorType::Mat4 ||
                accessor.componentType != fastgltf::ComponentType::Float ||
                accessor.count != skin.jointNodeIndices.size())
                return fail(ErrorCode::corruptData, "glTF inverse-bind matrices are invalid",
                            skin.name);
            fastgltf::iterateAccessorWithIndex<fastgltf::math::fmat4x4>(
                sourceAsset, accessor, [&](const auto& matrix, std::size_t index) {
                    skin.inverseBindMatrices[index] = toSimd(matrix);
                });
            if (std::ranges::any_of(skin.inverseBindMatrices, [](const simd_float4x4& matrix) {
                    return !std::isfinite(simd_determinant(matrix));
                }))
                return fail(ErrorCode::corruptData, "glTF inverse-bind matrix is not finite",
                            skin.name);
        }
        result.skins.push_back(std::move(skin));
    }
    if (sourceAsset.images.size() > limits.maximumImages)
        return fail(ErrorCode::resourceExhausted, "glTF exceeds image-count limit");
    std::size_t totalImageBytes = 0;
    result.images.reserve(sourceAsset.images.size());
    for (const auto& sourceImage : sourceAsset.images) {
        auto bytes = copyImageBytes(sourceAsset, sourceImage);
        if (!bytes)
            return std::unexpected(bytes.error());
        if (bytes->size() > limits.maximumImageBytes ||
            totalImageBytes > limits.maximumImageBytes - bytes->size()) {
            return fail(ErrorCode::resourceExhausted, "glTF exceeds encoded-image byte limit");
        }
        totalImageBytes += bytes->size();
        result.images.push_back(EncodedImage{
            sourceImage.name.empty() ? "Image" : std::string(sourceImage.name), std::move(*bytes)});
    }
    result.textures.reserve(sourceAsset.textures.size());
    for (const auto& sourceTexture : sourceAsset.textures) {
        if (!sourceTexture.imageIndex || *sourceTexture.imageIndex >= result.images.size()) {
            return fail(ErrorCode::unsupported, "glTF texture has no supported core image source");
        }
        TextureAsset texture;
        texture.imageIndex = *sourceTexture.imageIndex;
        if (sourceTexture.samplerIndex) {
            if (*sourceTexture.samplerIndex >= sourceAsset.samplers.size())
                return fail(ErrorCode::corruptData, "glTF texture sampler index is invalid");
            const auto& sampler = sourceAsset.samplers[*sourceTexture.samplerIndex];
            texture.addressU = addressMode(sampler.wrapS);
            texture.addressV = addressMode(sampler.wrapT);
            if (sampler.magFilter)
                texture.magnification = *sampler.magFilter == fastgltf::Filter::Nearest
                                            ? SamplerFilter::nearest
                                            : SamplerFilter::linear;
            if (sampler.minFilter)
                applyMinificationFilter(texture, *sampler.minFilter);
        }
        result.textures.push_back(texture);
    }
    result.materials.reserve(sourceAsset.materials.size() + 1);
    PbrMaterial defaultMaterial;
    defaultMaterial.name = "Default";
    result.materials.push_back(std::move(defaultMaterial));
    for (const auto& sourceMaterial : sourceAsset.materials) {
        PbrMaterial material;
        material.name = sourceMaterial.name.empty() ? "Material" : std::string(sourceMaterial.name);
        material.baseColor = {static_cast<float>(sourceMaterial.pbrData.baseColorFactor[0]),
                              static_cast<float>(sourceMaterial.pbrData.baseColorFactor[1]),
                              static_cast<float>(sourceMaterial.pbrData.baseColorFactor[2]),
                              static_cast<float>(sourceMaterial.pbrData.baseColorFactor[3])};
        material.emissive = {static_cast<float>(sourceMaterial.emissiveFactor[0]),
                             static_cast<float>(sourceMaterial.emissiveFactor[1]),
                             static_cast<float>(sourceMaterial.emissiveFactor[2])};
        material.metallic = static_cast<float>(sourceMaterial.pbrData.metallicFactor);
        material.roughness = static_cast<float>(sourceMaterial.pbrData.roughnessFactor);
        material.normalScale = sourceMaterial.normalTexture
                                   ? static_cast<float>(sourceMaterial.normalTexture->scale)
                                   : 1.0F;
        material.occlusionStrength =
            sourceMaterial.occlusionTexture
                ? static_cast<float>(sourceMaterial.occlusionTexture->strength)
                : 1.0F;
        material.alphaCutoff = static_cast<float>(sourceMaterial.alphaCutoff);
        material.doubleSided = sourceMaterial.doubleSided;
        material.alphaBlend = sourceMaterial.alphaMode == fastgltf::AlphaMode::Blend;
        material.alphaMask = sourceMaterial.alphaMode == fastgltf::AlphaMode::Mask;
        auto resolveTexture = [&](const auto& binding, std::size_t slot,
                                  const char* purpose) -> Result<std::optional<std::size_t>> {
            if (!binding)
                return std::optional<std::size_t>{};
            if (binding->textureIndex >= result.textures.size())
                return fail(ErrorCode::corruptData, "glTF material texture index is invalid",
                            purpose);
            const std::size_t textureCoordinates =
                binding->transform && binding->transform->texCoordIndex
                    ? *binding->transform->texCoordIndex
                    : binding->texCoordIndex;
            if (textureCoordinates != 0)
                return fail(ErrorCode::unsupported,
                            "AETHER currently requires texture bindings to use TEXCOORD_0",
                            purpose);
            if (binding->transform) {
                auto& transform = material.uvTransforms[slot];
                transform.scale = {static_cast<float>(binding->transform->uvScale[0]),
                                   static_cast<float>(binding->transform->uvScale[1])};
                transform.offset = {static_cast<float>(binding->transform->uvOffset[0]),
                                    static_cast<float>(binding->transform->uvOffset[1])};
                transform.rotation = static_cast<float>(binding->transform->rotation);
                if (!std::isfinite(transform.scale.x) || !std::isfinite(transform.scale.y) ||
                    !std::isfinite(transform.offset.x) || !std::isfinite(transform.offset.y) ||
                    !std::isfinite(transform.rotation))
                    return fail(ErrorCode::corruptData, "glTF texture transform is not finite",
                                purpose);
            }
            return std::optional<std::size_t>{binding->textureIndex};
        };
        auto baseColorTexture =
            resolveTexture(sourceMaterial.pbrData.baseColorTexture, 0, "base color");
        auto metallicRoughnessTexture = resolveTexture(
            sourceMaterial.pbrData.metallicRoughnessTexture, 1, "metallic roughness");
        auto normalTexture = resolveTexture(sourceMaterial.normalTexture, 2, "normal");
        auto occlusionTexture = resolveTexture(sourceMaterial.occlusionTexture, 3, "occlusion");
        auto emissiveTexture = resolveTexture(sourceMaterial.emissiveTexture, 4, "emissive");
        if (!baseColorTexture)
            return std::unexpected(baseColorTexture.error());
        if (!metallicRoughnessTexture)
            return std::unexpected(metallicRoughnessTexture.error());
        if (!normalTexture)
            return std::unexpected(normalTexture.error());
        if (!occlusionTexture)
            return std::unexpected(occlusionTexture.error());
        if (!emissiveTexture)
            return std::unexpected(emissiveTexture.error());
        material.baseColorTexture = *baseColorTexture;
        material.metallicRoughnessTexture = *metallicRoughnessTexture;
        material.normalTexture = *normalTexture;
        material.occlusionTexture = *occlusionTexture;
        material.emissiveTexture = *emissiveTexture;
        result.materials.push_back(std::move(material));
    }

    std::size_t totalVertices = 0;
    std::size_t totalIndices = 0;
    std::size_t totalMorphDeltaValues = 0;
    for (const auto& sourceMesh : sourceAsset.meshes) {
        for (const auto& sourcePrimitive : sourceMesh.primitives) {
            if (result.primitives.size() >= limits.maximumPrimitives) {
                return fail(ErrorCode::resourceExhausted, "glTF exceeds primitive limit");
            }
            if (sourcePrimitive.type != fastgltf::PrimitiveType::Triangles) {
                return fail(ErrorCode::unsupported,
                            "AETHER currently requires triangle primitives");
            }
            const auto* positionAttribute = sourcePrimitive.findAttribute("POSITION");
            if (positionAttribute == sourcePrimitive.attributes.end() ||
                !sourcePrimitive.indicesAccessor) {
                return fail(ErrorCode::corruptData,
                            "glTF primitive is missing positions or generated indices");
            }
            const auto& positionAccessor = sourceAsset.accessors[positionAttribute->accessorIndex];
            const auto& indexAccessor =
                sourceAsset.accessors[sourcePrimitive.indicesAccessor.value()];
            if (auto checked = checkGrowth(totalVertices, positionAccessor.count,
                                           limits.maximumVertices, "vertex");
                !checked) {
                return std::unexpected(checked.error());
            }
            if (auto checked =
                    checkGrowth(totalIndices, indexAccessor.count, limits.maximumIndices, "index");
                !checked) {
                return std::unexpected(checked.error());
            }

            MeshPrimitive primitive;
            primitive.name = sourceMesh.name.empty() ? "Primitive" : std::string(sourceMesh.name);
            primitive.materialIndex =
                sourcePrimitive.materialIndex ? sourcePrimitive.materialIndex.value() + 1 : 0;
            primitive.vertices.resize(positionAccessor.count);
            fastgltf::iterateAccessorWithIndex<fastgltf::math::fvec3>(
                sourceAsset, positionAccessor,
                [&](const fastgltf::math::fvec3& value, std::size_t index) {
                    primitive.vertices[index].position = {value.x(), value.y(), value.z()};
                });

            bool hasNormals = false;
            bool hasTextureCoordinates = false;
            bool hasTangents = false;
            bool hasJoints = false;
            bool hasWeights = false;
            if (const auto* normalAttribute = sourcePrimitive.findAttribute("NORMAL");
                normalAttribute != sourcePrimitive.attributes.end()) {
                const auto& accessor = sourceAsset.accessors[normalAttribute->accessorIndex];
                if (accessor.count != primitive.vertices.size()) {
                    return fail(ErrorCode::corruptData,
                                "glTF normal count does not match positions");
                }
                fastgltf::iterateAccessorWithIndex<fastgltf::math::fvec3>(
                    sourceAsset, accessor,
                    [&](const fastgltf::math::fvec3& value, std::size_t index) {
                        primitive.vertices[index].normal = {value.x(), value.y(), value.z()};
                    });
                hasNormals = true;
            }
            if (const auto* textureAttribute = sourcePrimitive.findAttribute("TEXCOORD_0");
                textureAttribute != sourcePrimitive.attributes.end()) {
                const auto& accessor = sourceAsset.accessors[textureAttribute->accessorIndex];
                if (accessor.count != primitive.vertices.size()) {
                    return fail(ErrorCode::corruptData,
                                "glTF texture-coordinate count does not match positions");
                }
                fastgltf::iterateAccessorWithIndex<fastgltf::math::fvec2>(
                    sourceAsset, accessor,
                    [&](const fastgltf::math::fvec2& value, std::size_t index) {
                        primitive.vertices[index].textureCoordinate = {value.x(), value.y()};
                    });
                hasTextureCoordinates = true;
            }
            if (const auto* colorAttribute = sourcePrimitive.findAttribute("COLOR_0");
                colorAttribute != sourcePrimitive.attributes.end()) {
                const auto& accessor = sourceAsset.accessors[colorAttribute->accessorIndex];
                const bool supportedComponent =
                    accessor.componentType == fastgltf::ComponentType::Float ||
                    ((accessor.componentType == fastgltf::ComponentType::UnsignedByte ||
                      accessor.componentType == fastgltf::ComponentType::UnsignedShort) &&
                     accessor.normalized);
                if (accessor.count != primitive.vertices.size() || !supportedComponent ||
                    (accessor.type != fastgltf::AccessorType::Vec3 &&
                     accessor.type != fastgltf::AccessorType::Vec4))
                    return fail(ErrorCode::corruptData, "glTF vertex-color accessor is invalid");
                primitive.vertexColors.resize(primitive.vertices.size());
                bool unsupportedAlpha = false;
                if (accessor.type == fastgltf::AccessorType::Vec3) {
                    fastgltf::iterateAccessorWithIndex<fastgltf::math::fvec3>(
                        sourceAsset, accessor, [&](const auto& value, std::size_t index) {
                            primitive.vertexColors[index] = {value.x(), value.y(), value.z()};
                        });
                } else {
                    fastgltf::iterateAccessorWithIndex<fastgltf::math::fvec4>(
                        sourceAsset, accessor, [&](const auto& value, std::size_t index) {
                            primitive.vertexColors[index] = {value.x(), value.y(), value.z()};
                            unsupportedAlpha =
                                unsupportedAlpha || std::abs(value.w() - 1.0F) > 1.0e-6F;
                        });
                }
                if (unsupportedAlpha)
                    return fail(ErrorCode::unsupported,
                                "AETHER mesh colors do not yet represent COLOR_0 alpha");
                if (std::ranges::any_of(primitive.vertexColors, [](simd_float3 color) {
                        return !std::isfinite(color.x) || !std::isfinite(color.y) ||
                               !std::isfinite(color.z) || color.x < 0.0F || color.x > 1.0F ||
                               color.y < 0.0F || color.y > 1.0F || color.z < 0.0F || color.z > 1.0F;
                    }))
                    return fail(ErrorCode::corruptData,
                                "glTF vertex color is outside linear zero-to-one range");
            }
            if (const auto* tangentAttribute = sourcePrimitive.findAttribute("TANGENT");
                tangentAttribute != sourcePrimitive.attributes.end()) {
                const auto& accessor = sourceAsset.accessors[tangentAttribute->accessorIndex];
                if (accessor.count != primitive.vertices.size())
                    return fail(ErrorCode::corruptData,
                                "glTF tangent count does not match positions");
                fastgltf::iterateAccessorWithIndex<fastgltf::math::fvec4>(
                    sourceAsset, accessor,
                    [&](const fastgltf::math::fvec4& value, std::size_t index) {
                        primitive.vertices[index].tangent = {value.x(), value.y(), value.z(),
                                                             value.w()};
                    });
                hasTangents = true;
            }
            if (const auto* jointAttribute = sourcePrimitive.findAttribute("JOINTS_0");
                jointAttribute != sourcePrimitive.attributes.end()) {
                const auto& accessor = sourceAsset.accessors[jointAttribute->accessorIndex];
                if (accessor.count != primitive.vertices.size())
                    return fail(ErrorCode::corruptData,
                                "glTF joint count does not match positions");
                fastgltf::iterateAccessorWithIndex<fastgltf::math::uvec4>(
                    sourceAsset, accessor, [&](const auto& value, std::size_t index) {
                        primitive.vertices[index].joints = {static_cast<std::uint32_t>(value.x()),
                                                            static_cast<std::uint32_t>(value.y()),
                                                            static_cast<std::uint32_t>(value.z()),
                                                            static_cast<std::uint32_t>(value.w())};
                    });
                hasJoints = true;
            }
            if (const auto* weightAttribute = sourcePrimitive.findAttribute("WEIGHTS_0");
                weightAttribute != sourcePrimitive.attributes.end()) {
                const auto& accessor = sourceAsset.accessors[weightAttribute->accessorIndex];
                if (accessor.count != primitive.vertices.size())
                    return fail(ErrorCode::corruptData,
                                "glTF weight count does not match positions");
                fastgltf::iterateAccessorWithIndex<fastgltf::math::fvec4>(
                    sourceAsset, accessor, [&](const auto& value, std::size_t index) {
                        primitive.vertices[index].weights = {value.x(), value.y(), value.z(),
                                                             value.w()};
                    });
                hasWeights = true;
            }
            if (hasJoints != hasWeights)
                return fail(ErrorCode::corruptData,
                            "glTF skin attributes must provide JOINTS_0 and WEIGHTS_0 together");
            if (hasWeights) {
                for (auto& vertex : primitive.vertices) {
                    for (std::size_t component = 0; component < 4; ++component)
                        if (!std::isfinite(vertex.weights[component]) ||
                            vertex.weights[component] < 0.0F)
                            return fail(ErrorCode::corruptData, "glTF skin weight is invalid");
                    const float sum = simd_reduce_add(vertex.weights);
                    if (sum <= 1.0e-8F)
                        return fail(ErrorCode::corruptData, "glTF skin weights sum to zero");
                    vertex.weights /= sum;
                }
                primitive.hasSkinAttributes = true;
            }

            primitive.indices.resize(indexAccessor.count);
            fastgltf::copyFromAccessor<std::uint32_t>(sourceAsset, indexAccessor,
                                                      primitive.indices.data());
            if (std::ranges::any_of(primitive.indices, [&](std::uint32_t index) {
                    return index >= primitive.vertices.size();
                })) {
                return fail(ErrorCode::corruptData, "glTF primitive contains an invalid index");
            }
            if (!hasNormals)
                generateNormals(primitive);
            const auto& primitiveMaterial = result.materials.at(primitive.materialIndex);
            if (!hasTextureCoordinates &&
                (primitiveMaterial.baseColorTexture || primitiveMaterial.metallicRoughnessTexture ||
                 primitiveMaterial.normalTexture || primitiveMaterial.occlusionTexture ||
                 primitiveMaterial.emissiveTexture)) {
                return fail(ErrorCode::corruptData,
                            "glTF textured primitive is missing TEXCOORD_0");
            }
            if (!hasTangents)
                generateTangents(primitive);
            if (sourcePrimitive.targets.size() > limits.maximumMorphTargetsPerPrimitive)
                return fail(ErrorCode::resourceExhausted,
                            "glTF primitive exceeds morph-target limit");
            primitive.morphTargets.reserve(sourcePrimitive.targets.size());
            for (std::size_t targetIndex = 0; targetIndex < sourcePrimitive.targets.size();
                 ++targetIndex) {
                if (sourcePrimitive.targets[targetIndex].empty())
                    return fail(ErrorCode::corruptData, "glTF morph target has no attributes");
                if (primitive.vertices.size() > limits.maximumMorphDeltaValues / 3 ||
                    primitive.vertices.size() * 3 >
                        limits.maximumMorphDeltaValues - totalMorphDeltaValues)
                    return fail(ErrorCode::resourceExhausted,
                                "glTF exceeds morph-delta allocation limit");
                totalMorphDeltaValues += primitive.vertices.size() * 3;
                MeshPrimitive::MorphTarget target;
                target.positionDeltas.assign(primitive.vertices.size(), simd_float3{});
                target.normalDeltas.assign(primitive.vertices.size(), simd_float3{});
                target.tangentDeltas.assign(primitive.vertices.size(), simd_float3{});
                auto loadDeltas = [&](std::string_view semantic,
                                      std::vector<simd_float3>& destination) -> Result<void> {
                    const auto* attribute =
                        sourcePrimitive.findTargetAttribute(targetIndex, semantic);
                    if (attribute == sourcePrimitive.targets[targetIndex].end())
                        return {};
                    const auto& accessor = sourceAsset.accessors[attribute->accessorIndex];
                    if (accessor.count != primitive.vertices.size() ||
                        accessor.type != fastgltf::AccessorType::Vec3 ||
                        accessor.componentType != fastgltf::ComponentType::Float)
                        return fail(ErrorCode::corruptData, "glTF morph target accessor is invalid",
                                    std::string(semantic));
                    fastgltf::iterateAccessorWithIndex<fastgltf::math::fvec3>(
                        sourceAsset, accessor, [&](const auto& value, std::size_t index) {
                            destination[index] = {value.x(), value.y(), value.z()};
                        });
                    if (std::ranges::any_of(destination, [](simd_float3 value) {
                            return !std::isfinite(value.x) || !std::isfinite(value.y) ||
                                   !std::isfinite(value.z);
                        }))
                        return fail(ErrorCode::corruptData, "glTF morph deltas must be finite");
                    return {};
                };
                if (auto loadedDeltas = loadDeltas("POSITION", target.positionDeltas);
                    !loadedDeltas)
                    return std::unexpected(loadedDeltas.error());
                if (auto loadedDeltas = loadDeltas("NORMAL", target.normalDeltas); !loadedDeltas)
                    return std::unexpected(loadedDeltas.error());
                if (auto loadedDeltas = loadDeltas("TANGENT", target.tangentDeltas); !loadedDeltas)
                    return std::unexpected(loadedDeltas.error());
                primitive.morphTargets.push_back(std::move(target));
            }
            if (sourceMesh.weights.empty()) {
                primitive.defaultMorphWeights.assign(primitive.morphTargets.size(), 0.0F);
            } else {
                if (sourceMesh.weights.size() != primitive.morphTargets.size())
                    return fail(ErrorCode::corruptData,
                                "glTF mesh morph-weight count does not match targets");
                primitive.defaultMorphWeights.reserve(sourceMesh.weights.size());
                for (const auto weight : sourceMesh.weights) {
                    const float converted = static_cast<float>(weight);
                    if (!std::isfinite(converted))
                        return fail(ErrorCode::corruptData, "glTF morph weight is not finite");
                    primitive.defaultMorphWeights.push_back(converted);
                }
            }
            simd_float3 minimum = primitive.vertices.front().position;
            simd_float3 maximum = minimum;
            for (const auto& vertex : primitive.vertices) {
                minimum = simd_min(minimum, vertex.position);
                maximum = simd_max(maximum, vertex.position);
            }
            primitive.localBoundsCenter = (minimum + maximum) * 0.5F;
            totalVertices += primitive.vertices.size();
            totalIndices += primitive.indices.size();
            result.primitives.push_back(std::move(primitive));
        }
    }

    if (result.primitives.empty()) {
        return fail(ErrorCode::corruptData, "glTF contains no renderable triangle primitives");
    }
    if (sourceAsset.scenes.empty())
        return fail(ErrorCode::corruptData, "glTF contains no scene to instantiate");
    const std::size_t sceneIndex = sourceAsset.defaultScene.value_or(0);
    if (sceneIndex >= sourceAsset.scenes.size())
        return fail(ErrorCode::corruptData, "glTF default scene index is invalid");

    std::vector<std::size_t> firstPrimitive(sourceAsset.meshes.size());
    std::size_t primitiveOffset = 0;
    for (std::size_t meshIndex = 0; meshIndex < sourceAsset.meshes.size(); ++meshIndex) {
        firstPrimitive[meshIndex] = primitiveOffset;
        primitiveOffset += sourceAsset.meshes[meshIndex].primitives.size();
    }
    bool instanceOverflow = false;
    bool singularTransform = false;
    bool invalidInstance = false;
    fastgltf::iterateSceneNodes(
        sourceAsset, sceneIndex, fastgltf::math::fmat4x4{},
        [&](const fastgltf::Node& node, const fastgltf::math::fmat4x4& worldTransform) {
            if (!node.meshIndex || *node.meshIndex >= sourceAsset.meshes.size())
                return;
            const auto meshIndex = *node.meshIndex;
            const auto count = sourceAsset.meshes[meshIndex].primitives.size();
            if (node.skinIndex && *node.skinIndex >= result.skins.size()) {
                invalidInstance = true;
                return;
            }
            const auto transform = toSimd(worldTransform);
            const float determinant = simd_determinant(transform);
            if (!std::isfinite(determinant) || std::abs(determinant) < 1.0e-8F) {
                singularTransform = true;
                return;
            }
            for (std::size_t localPrimitive = 0; localPrimitive < count; ++localPrimitive) {
                if (result.instances.size() >= limits.maximumInstances) {
                    instanceOverflow = true;
                    return;
                }
                const auto primitiveIndex = firstPrimitive[meshIndex] + localPrimitive;
                const auto& primitive = result.primitives[primitiveIndex];
                if (node.skinIndex) {
                    if (!primitive.hasSkinAttributes) {
                        invalidInstance = true;
                        return;
                    }
                    const auto jointCount = result.skins[*node.skinIndex].jointNodeIndices.size();
                    for (const auto& vertex : primitive.vertices)
                        for (std::size_t component = 0; component < 4; ++component)
                            if (vertex.weights[component] > 0.0F &&
                                vertex.joints[component] >= jointCount) {
                                invalidInstance = true;
                                return;
                            }
                }
                const auto nodeIndex = static_cast<std::size_t>(&node - sourceAsset.nodes.data());
                std::vector<float> morphWeights = primitive.defaultMorphWeights;
                if (!node.weights.empty()) {
                    if (node.weights.size() != primitive.morphTargets.size()) {
                        invalidInstance = true;
                        return;
                    }
                    morphWeights.clear();
                    morphWeights.reserve(node.weights.size());
                    for (const auto weight : node.weights) {
                        const float converted = static_cast<float>(weight);
                        if (!std::isfinite(converted)) {
                            invalidInstance = true;
                            return;
                        }
                        morphWeights.push_back(converted);
                    }
                }
                result.instances.push_back(MeshInstance{
                    node.name.empty() ? std::string(sourceAsset.meshes[meshIndex].name)
                                      : std::string(node.name),
                    firstPrimitive[meshIndex] + localPrimitive, transform, nodeIndex,
                    node.skinIndex ? std::optional<std::size_t>{*node.skinIndex} : std::nullopt,
                    std::move(morphWeights)});
            }
        });
    if (instanceOverflow) {
        return fail(ErrorCode::resourceExhausted, "glTF exceeds scene-instance limit");
    }
    if (singularTransform)
        return fail(ErrorCode::corruptData, "glTF mesh node has a singular world transform");
    if (invalidInstance)
        return fail(ErrorCode::corruptData,
                    "glTF mesh instance has invalid skin, joint attributes, or morph weights");
    if (result.instances.empty())
        return fail(ErrorCode::corruptData, "glTF scene contains no renderable mesh instances");

    std::size_t totalAnimationChannels = 0;
    std::size_t totalAnimationKeyframes = 0;
    result.animations.reserve(sourceAsset.animations.size());
    for (const auto& sourceAnimation : sourceAsset.animations) {
        AnimationClip clip;
        clip.name = sourceAnimation.name.empty()
                        ? "Animation " + std::to_string(result.animations.size())
                        : std::string(sourceAnimation.name);
        if (sourceAnimation.channels.size() >
            limits.maximumAnimationChannels - totalAnimationChannels)
            return fail(ErrorCode::resourceExhausted, "glTF exceeds animation-channel limit");
        totalAnimationChannels += sourceAnimation.channels.size();
        clip.channels.reserve(sourceAnimation.channels.size());
        for (const auto& sourceChannel : sourceAnimation.channels) {
            if (!sourceChannel.nodeIndex || *sourceChannel.nodeIndex >= result.nodes.size() ||
                sourceChannel.samplerIndex >= sourceAnimation.samplers.size())
                return fail(ErrorCode::corruptData, "glTF animation channel reference is invalid");
            const auto& sampler = sourceAnimation.samplers[sourceChannel.samplerIndex];
            if (sampler.inputAccessor >= sourceAsset.accessors.size() ||
                sampler.outputAccessor >= sourceAsset.accessors.size())
                return fail(ErrorCode::corruptData, "glTF animation accessor reference is invalid");
            const auto& input = sourceAsset.accessors[sampler.inputAccessor];
            const auto& output = sourceAsset.accessors[sampler.outputAccessor];
            if (input.type != fastgltf::AccessorType::Scalar ||
                input.componentType != fastgltf::ComponentType::Float)
                return fail(ErrorCode::corruptData, "glTF animation times must be scalar floats");
            if (input.count == 0 ||
                input.count > limits.maximumAnimationKeyframes - totalAnimationKeyframes)
                return fail(ErrorCode::resourceExhausted, "glTF exceeds animation-keyframe limit");
            totalAnimationKeyframes += input.count;
            AnimationChannel channel;
            channel.nodeIndex = *sourceChannel.nodeIndex;
            switch (sourceChannel.path) {
            case fastgltf::AnimationPath::Translation:
                channel.path = AnimationPath::translation;
                break;
            case fastgltf::AnimationPath::Rotation:
                channel.path = AnimationPath::rotation;
                break;
            case fastgltf::AnimationPath::Scale:
                channel.path = AnimationPath::scale;
                break;
            default:
                return fail(ErrorCode::unsupported,
                            "glTF morph-weight animation is not implemented");
            }
            switch (sampler.interpolation) {
            case fastgltf::AnimationInterpolation::Step:
                channel.interpolation = AnimationInterpolation::step;
                break;
            case fastgltf::AnimationInterpolation::Linear:
                channel.interpolation = AnimationInterpolation::linear;
                break;
            case fastgltf::AnimationInterpolation::CubicSpline:
                channel.interpolation = AnimationInterpolation::cubicSpline;
                break;
            }
            channel.keyTimes.resize(input.count);
            fastgltf::copyFromAccessor<float>(sourceAsset, input, channel.keyTimes.data());
            if (!std::is_sorted(channel.keyTimes.begin(), channel.keyTimes.end()) ||
                std::adjacent_find(channel.keyTimes.begin(), channel.keyTimes.end()) !=
                    channel.keyTimes.end() ||
                std::ranges::any_of(channel.keyTimes,
                                    [](float time) { return !std::isfinite(time); }))
                return fail(ErrorCode::corruptData,
                            "glTF animation times must be finite and increasing");
            const std::size_t multiplier =
                channel.interpolation == AnimationInterpolation::cubicSpline ? 3 : 1;
            if (output.count != input.count * multiplier)
                return fail(ErrorCode::corruptData, "glTF animation output count is invalid");
            channel.values.resize(output.count);
            if (channel.path == AnimationPath::rotation) {
                if (output.type != fastgltf::AccessorType::Vec4)
                    return fail(ErrorCode::corruptData,
                                "glTF rotation animation must use VEC4 values");
                fastgltf::iterateAccessorWithIndex<fastgltf::math::fvec4>(
                    sourceAsset, output, [&](const auto& value, std::size_t index) {
                        channel.values[index] = {value.x(), value.y(), value.z(), value.w()};
                    });
            } else {
                if (output.type != fastgltf::AccessorType::Vec3)
                    return fail(ErrorCode::corruptData, "glTF TRS animation must use VEC3 values");
                fastgltf::iterateAccessorWithIndex<fastgltf::math::fvec3>(
                    sourceAsset, output, [&](const auto& value, std::size_t index) {
                        channel.values[index] = {value.x(), value.y(), value.z(), 0.0F};
                    });
            }
            if (std::ranges::any_of(channel.values, [](simd_float4 value) {
                    return !std::isfinite(value.x) || !std::isfinite(value.y) ||
                           !std::isfinite(value.z) || !std::isfinite(value.w);
                }))
                return fail(ErrorCode::corruptData, "glTF animation values must be finite");
            if (channel.path == AnimationPath::rotation) {
                for (std::size_t key = 0; key < channel.keyTimes.size(); ++key) {
                    const std::size_t valueIndex =
                        channel.interpolation == AnimationInterpolation::cubicSpline ? key * 3 + 1
                                                                                     : key;
                    if (simd_length_squared(channel.values[valueIndex]) < 1.0e-12F)
                        return fail(ErrorCode::corruptData,
                                    "glTF rotation animation contains a zero quaternion");
                    channel.values[valueIndex] = simd_normalize(channel.values[valueIndex]);
                }
            }
            clip.durationSeconds = std::max(clip.durationSeconds, channel.keyTimes.back());
            clip.channels.push_back(std::move(channel));
        }
        result.animations.push_back(std::move(clip));
    }
    return result;
}

Result<MeshAsset> GltfLoader::load(const std::filesystem::path& path, const GltfLimits& limits) {
    std::error_code filesystemError;
    const auto fileBytes = std::filesystem::file_size(path, filesystemError);
    if (filesystemError)
        return fail(ErrorCode::notFound, "Unable to read glTF file", path.string());
    if (fileBytes == 0 || fileBytes > limits.maximumFileBytes)
        return fail(ErrorCode::resourceExhausted, "glTF file size is empty or exceeds its limit",
                    path.string());

    auto source = fastgltf::MappedGltfFile::FromPath(path);
    if (!source)
        return fail(ErrorCode::corruptData, "Unable to map glTF file",
                    std::string(fastgltf::getErrorMessage(source.error())));
    return loadData(source.get(), path.parent_path(), path.stem().string(), limits);
}

Result<MeshAsset> GltfLoader::load(std::span<const std::byte> bytes,
                                   std::string_view diagnosticName, const GltfLimits& limits) {
    if (bytes.empty() || bytes.size() > limits.maximumFileBytes)
        return fail(ErrorCode::resourceExhausted, "glTF payload is empty or exceeds its limit",
                    std::string(diagnosticName));
    auto source = fastgltf::GltfDataBuffer::FromBytes(bytes.data(), bytes.size());
    if (!source)
        return fail(ErrorCode::corruptData, "Unable to copy glTF payload",
                    std::string(fastgltf::getErrorMessage(source.error())));
    return loadData(source.get(), std::filesystem::path{"."}, diagnosticName, limits);
}

} // namespace aether::mesh
