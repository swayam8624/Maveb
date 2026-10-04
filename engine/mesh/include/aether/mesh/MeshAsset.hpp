#pragma once

#include <aether/scene/Transform.hpp>
#include <shared/AetherShaderTypes.h>
#include <simd/simd.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <optional>
#include <string>
#include <vector>

namespace aether::mesh {

using MeshVertex = AetherMeshVertex;

static_assert(offsetof(MeshVertex, position) == 0);
static_assert(offsetof(MeshVertex, normal) == 16);
static_assert(offsetof(MeshVertex, tangent) == 32);
static_assert(offsetof(MeshVertex, textureCoordinate) == 48);
static_assert(offsetof(MeshVertex, joints) == 64);
static_assert(offsetof(MeshVertex, weights) == 80);

enum class SamplerFilter { nearest, linear };
enum class SamplerMipFilter { none, nearest, linear };
enum class SamplerAddressMode { clampToEdge, repeat, mirroredRepeat };

struct EncodedImage final {
    std::string name;
    std::vector<std::byte> bytes;
};

struct TextureAsset final {
    std::size_t imageIndex{};
    SamplerFilter magnification{SamplerFilter::linear};
    SamplerFilter minification{SamplerFilter::linear};
    SamplerMipFilter mipFilter{SamplerMipFilter::none};
    SamplerAddressMode addressU{SamplerAddressMode::repeat};
    SamplerAddressMode addressV{SamplerAddressMode::repeat};
};

struct PbrMaterial final {
    struct UvTransform final {
        simd_float2 scale{1.0F, 1.0F};
        simd_float2 offset{};
        float rotation{};
    };
    std::string name;
    simd_float4 baseColor{1.0F, 1.0F, 1.0F, 1.0F};
    simd_float3 emissive{};
    float metallic{1.0F};
    float roughness{1.0F};
    float normalScale{1.0F};
    float occlusionStrength{1.0F};
    float alphaCutoff{0.5F};
    bool doubleSided{};
    bool alphaBlend{};
    bool alphaMask{};
    std::optional<std::size_t> baseColorTexture;
    std::optional<std::size_t> metallicRoughnessTexture;
    std::optional<std::size_t> normalTexture;
    std::optional<std::size_t> occlusionTexture;
    std::optional<std::size_t> emissiveTexture;
    std::array<UvTransform, 5> uvTransforms{};
};

struct MeshPrimitive final {
    struct MorphTarget final {
        std::vector<simd_float3> positionDeltas;
        std::vector<simd_float3> normalDeltas;
        std::vector<simd_float3> tangentDeltas;
    };
    std::string name;
    std::vector<MeshVertex> vertices;
    std::vector<std::uint32_t> indices;
    /// Optional linear RGB colors owned by geometry-producing tools.
    /// Empty means the material base color applies; otherwise it must match vertices.
    std::vector<simd_float3> vertexColors;
    std::size_t materialIndex{};
    simd_float3 localBoundsCenter{};
    bool hasSkinAttributes{};
    std::vector<MorphTarget> morphTargets;
    std::vector<float> defaultMorphWeights;
};

/// One scene-node use of a mesh primitive. Geometry remains shared across instances.
struct MeshInstance final {
    std::string name;
    std::size_t primitiveIndex{};
    simd_float4x4 worldTransform{matrix_identity_float4x4};
    std::size_t nodeIndex{};
    std::optional<std::size_t> skinIndex;
    std::vector<float> morphWeights;
};

struct MeshSkin final {
    std::string name;
    std::vector<std::size_t> jointNodeIndices;
    std::vector<simd_float4x4> inverseBindMatrices;
};

struct SceneNode final {
    std::string name;
    scene::Transform localTransform;
    std::optional<std::size_t> parentIndex;
    std::vector<std::size_t> children;
};

enum class AnimationPath { translation, rotation, scale };
enum class AnimationInterpolation { step, linear, cubicSpline };

struct AnimationChannel final {
    std::size_t nodeIndex{};
    AnimationPath path{AnimationPath::translation};
    AnimationInterpolation interpolation{AnimationInterpolation::linear};
    std::vector<float> keyTimes;
    /// LINEAR/STEP: one value per key. CUBICSPLINE: in tangent, value, out tangent per key.
    std::vector<simd_float4> values;
};

struct AnimationClip final {
    std::string name;
    float durationSeconds{};
    std::vector<AnimationChannel> channels;
};

struct MeshAsset final {
    std::string name;
    /// Slot zero is the engine's implicit glTF default and is never authored as a material.
    /// Imported or generated authored materials begin at slot one.
    std::vector<PbrMaterial> materials;
    std::vector<EncodedImage> images;
    std::vector<TextureAsset> textures;
    std::vector<MeshPrimitive> primitives;
    std::vector<MeshInstance> instances;
    std::vector<SceneNode> nodes;
    std::vector<AnimationClip> animations;
    std::vector<MeshSkin> skins;

    [[nodiscard]] std::size_t vertexCount() const noexcept;
    [[nodiscard]] std::size_t indexCount() const noexcept;
};

} // namespace aether::mesh
