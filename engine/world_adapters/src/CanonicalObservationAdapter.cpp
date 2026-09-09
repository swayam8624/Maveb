#include <aether/world_adapters/CanonicalObservationAdapter.hpp>

#include <aether/mesh/GltfLoader.hpp>

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <limits>
#include <string>
#include <vector>

namespace aether::world_adapters {
namespace {

class StableHash final {
  public:
    void addByte(std::uint8_t value) noexcept {
        value_ ^= value;
        value_ *= 1099511628211ULL;
    }

    void addUnsigned(std::uint64_t value) noexcept {
        for (std::uint32_t shift = 0; shift < 64; shift += 8)
            addByte(static_cast<std::uint8_t>((value >> shift) & 0xFFU));
    }

    void addFloat(float value) noexcept {
        addUnsigned(std::bit_cast<std::uint32_t>(value));
    }

    void addString(const std::string& value) noexcept {
        addUnsigned(value.size());
        for (const unsigned char character : value)
            addByte(character);
    }

    [[nodiscard]] std::uint64_t value() const noexcept {
        return value_;
    }

  private:
    std::uint64_t value_{14695981039346656037ULL};
};

struct LocalBounds final {
    simd_float3 minimum{};
    simd_float3 maximum{};
};

[[nodiscard]] Result<LocalBounds> primitiveBounds(const mesh::MeshPrimitive& primitive) {
    if (primitive.vertices.empty())
        return fail(ErrorCode::corruptData, "Canonical mesh primitive contains no vertices");

    const auto& first = primitive.vertices.front().position;
    LocalBounds bounds{{first.x, first.y, first.z}, {first.x, first.y, first.z}};
    for (const mesh::MeshVertex& vertex : primitive.vertices) {
        const simd_float3 position{vertex.position.x, vertex.position.y, vertex.position.z};
        bounds.minimum = simd_min(bounds.minimum, position);
        bounds.maximum = simd_max(bounds.maximum, position);
    }
    return bounds;
}

[[nodiscard]] world::Bounds transformedBounds(const LocalBounds& local, simd_float4x4 transform) {
    world::Bounds result;
    result.minimum = simd_float3{std::numeric_limits<float>::infinity(),
                                 std::numeric_limits<float>::infinity(),
                                 std::numeric_limits<float>::infinity()};
    result.maximum = -result.minimum;

    for (std::uint32_t corner = 0; corner < 8; ++corner) {
        const simd_float3 localPoint{
            (corner & 1U) != 0 ? local.maximum.x : local.minimum.x,
            (corner & 2U) != 0 ? local.maximum.y : local.minimum.y,
            (corner & 4U) != 0 ? local.maximum.z : local.minimum.z,
        };
        const simd_float4 worldPoint = simd_mul(
            transform, simd_float4{localPoint.x, localPoint.y, localPoint.z, 1.0F});
        const simd_float3 point{worldPoint.x, worldPoint.y, worldPoint.z};
        result.minimum = simd_min(result.minimum, point);
        result.maximum = simd_max(result.maximum, point);
    }
    return result;
}

[[nodiscard]] std::uint64_t geometrySignature(const mesh::MeshPrimitive& primitive) noexcept {
    StableHash hash;
    hash.addUnsigned(primitive.vertices.size());
    hash.addUnsigned(primitive.indices.size());
    for (const mesh::MeshVertex& vertex : primitive.vertices) {
        hash.addFloat(vertex.position.x);
        hash.addFloat(vertex.position.y);
        hash.addFloat(vertex.position.z);
    }
    for (const std::uint32_t index : primitive.indices)
        hash.addUnsigned(index);
    return hash.value();
}

void addOptionalIndex(StableHash& hash, const std::optional<std::size_t>& value) noexcept {
    hash.addUnsigned(value.has_value() ? 1U : 0U);
    if (value)
        hash.addUnsigned(*value);
}

[[nodiscard]] std::uint64_t appearanceSignature(const mesh::MeshAsset& asset,
                                                 const mesh::MeshPrimitive& primitive) noexcept {
    StableHash hash;
    hash.addUnsigned(primitive.materialIndex);
    if (primitive.materialIndex < asset.materials.size()) {
        const mesh::PbrMaterial& material = asset.materials[primitive.materialIndex];
        hash.addString(material.name);
        hash.addFloat(material.baseColor.x);
        hash.addFloat(material.baseColor.y);
        hash.addFloat(material.baseColor.z);
        hash.addFloat(material.baseColor.w);
        hash.addFloat(material.emissive.x);
        hash.addFloat(material.emissive.y);
        hash.addFloat(material.emissive.z);
        hash.addFloat(material.metallic);
        hash.addFloat(material.roughness);
        hash.addFloat(material.normalScale);
        hash.addFloat(material.occlusionStrength);
        hash.addFloat(material.alphaCutoff);
        hash.addUnsigned(material.doubleSided ? 1U : 0U);
        hash.addUnsigned(material.alphaBlend ? 1U : 0U);
        hash.addUnsigned(material.alphaMask ? 1U : 0U);
        addOptionalIndex(hash, material.baseColorTexture);
        addOptionalIndex(hash, material.metallicRoughnessTexture);
        addOptionalIndex(hash, material.normalTexture);
        addOptionalIndex(hash, material.occlusionTexture);
        addOptionalIndex(hash, material.emissiveTexture);
    }
    hash.addUnsigned(primitive.vertexColors.size());
    for (const simd_float3 color : primitive.vertexColors) {
        hash.addFloat(color.x);
        hash.addFloat(color.y);
        hash.addFloat(color.z);
    }
    return hash.value();
}

[[nodiscard]] Result<float> canonicalConfidence(const canonical::CanonicalAssetPayload& asset,
                                                float fallback) {
    if (!std::isfinite(fallback) || fallback < 0.0F || fallback > 1.0F) {
        return fail(ErrorCode::invalidArgument,
                    "Canonical observation fallback confidence must be in [0, 1]");
    }
    if (asset.manifest.confidenceSource == canonical::ConfidenceSource::uniform)
        return asset.manifest.uniformConfidence;
    if (asset.confidenceBytes.empty())
        return fallback;

    auto confidence = canonical::ConfidenceCodec::decode(asset.confidenceBytes);
    if (!confidence)
        return std::unexpected(confidence.error());
    if (confidence->empty())
        return fallback;
    double total{};
    for (const float value : *confidence)
        total += value;
    return static_cast<float>(total / static_cast<double>(confidence->size()));
}

[[nodiscard]] std::string instanceName(const mesh::MeshInstance& instance,
                                       const mesh::MeshPrimitive& primitive,
                                       std::size_t index) {
    if (!instance.name.empty())
        return instance.name;
    if (!primitive.name.empty())
        return primitive.name;
    return "captured-instance-" + std::to_string(index);
}

} // namespace

Result<std::vector<world::EntityState>>
observationsFromCanonicalAsset(const canonical::CanonicalAssetPayload& asset,
                               world::TimestampNs timestamp, CanonicalObservationConfig config) {
    if (timestamp == 0)
        return fail(ErrorCode::invalidArgument, "Canonical observation timestamp cannot be zero");

    auto confidence = canonicalConfidence(asset, config.fallbackConfidence);
    if (!confidence)
        return std::unexpected(confidence.error());

    auto loaded = mesh::GltfLoader::load(asset.meshBytes, asset.manifest.name);
    if (!loaded)
        return std::unexpected(loaded.error());
    if (loaded->instances.empty() && !loaded->primitives.empty()) {
        return fail(ErrorCode::corruptData,
                    "Canonical mesh contains geometry but no renderable scene instances");
    }

    std::vector<LocalBounds> localBounds;
    std::vector<std::uint64_t> geometrySignatures;
    std::vector<std::uint64_t> appearanceSignatures;
    localBounds.reserve(loaded->primitives.size());
    geometrySignatures.reserve(loaded->primitives.size());
    appearanceSignatures.reserve(loaded->primitives.size());
    for (const mesh::MeshPrimitive& primitive : loaded->primitives) {
        auto bounds = primitiveBounds(primitive);
        if (!bounds)
            return std::unexpected(bounds.error());
        localBounds.push_back(*bounds);
        geometrySignatures.push_back(geometrySignature(primitive));
        appearanceSignatures.push_back(appearanceSignature(*loaded, primitive));
    }

    std::vector<world::EntityState> observations;
    observations.reserve(loaded->instances.size());
    for (std::size_t index = 0; index < loaded->instances.size(); ++index) {
        const mesh::MeshInstance& instance = loaded->instances[index];
        if (instance.primitiveIndex >= loaded->primitives.size()) {
            return fail(ErrorCode::corruptData,
                        "Canonical mesh instance references an invalid primitive index");
        }
        const mesh::MeshPrimitive& primitive = loaded->primitives[instance.primitiveIndex];
        auto transform = scene::decomposeTransform(instance.worldTransform);
        if (!transform)
            return std::unexpected(transform.error());

        world::EntityState observation;
        observation.name = instanceName(instance, primitive, index);
        observation.semanticLabel = config.semanticLabel;
        observation.transform = *transform;
        observation.worldBounds = transformedBounds(localBounds[instance.primitiveIndex],
                                                    instance.worldTransform);
        observation.representation = world::RepresentationKind::mesh;
        observation.geometrySignature = geometrySignatures[instance.primitiveIndex];
        observation.appearanceSignature = appearanceSignatures[instance.primitiveIndex];
        observation.confidence = *confidence;
        observation.lastObserved = timestamp;
        observations.push_back(std::move(observation));
    }
    return observations;
}

} // namespace aether::world_adapters
