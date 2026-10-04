#pragma once

#include <aether/core/Error.hpp>
#include <aether/mesh/MeshAsset.hpp>

#include <cstddef>
#include <filesystem>
#include <span>
#include <string_view>

namespace aether::mesh {

struct GltfLimits final {
    std::uintmax_t maximumFileBytes{1ULL * 1024ULL * 1024ULL * 1024ULL};
    std::size_t maximumPrimitives{1'000'000};
    std::size_t maximumInstances{1'000'000};
    std::size_t maximumVertices{50'000'000};
    std::size_t maximumIndices{150'000'000};
    std::size_t maximumImages{100'000};
    std::size_t maximumImageBytes{1ULL * 1024ULL * 1024ULL * 1024ULL};
    std::size_t maximumAnimationChannels{1'000'000};
    std::size_t maximumAnimationKeyframes{10'000'000};
    std::size_t maximumSkins{100'000};
    std::size_t maximumJoints{1'000'000};
    std::size_t maximumMorphTargetsPerPrimitive{64};
    std::size_t maximumMorphDeltaValues{100'000'000};
};

class GltfLoader final {
  public:
    /// Input: local `.gltf` or `.glb` path and explicit allocation limits.
    /// Output: validated, indexed triangle primitives and metallic-roughness material factors.
    /// Task: isolate fastgltf and untrusted-file handling from renderer/GPU ownership.
    [[nodiscard]] static Result<MeshAsset> load(const std::filesystem::path& path,
                                                const GltfLimits& limits = {});

    /// Input: complete in-memory `.glb` bytes, a diagnostic name, and explicit limits.
    /// Output: the same validated renderable asset produced by the filesystem loader.
    /// Task: validate self-contained package payloads without temporary files or path access.
    [[nodiscard]] static Result<MeshAsset> load(std::span<const std::byte> bytes,
                                                std::string_view diagnosticName,
                                                const GltfLimits& limits = {});
};

} // namespace aether::mesh
