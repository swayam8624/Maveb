#pragma once

#include <aether/core/Error.hpp>
#include <aether/mesh/MeshAsset.hpp>

#include <cstddef>
#include <cstdint>
#include <filesystem>

namespace aether::mesh {

struct GltfExportLimits final {
    std::size_t maximumVertices{50'000'000};
    std::size_t maximumIndices{150'000'000};
    std::size_t maximumPrimitives{1'000'000};
    std::size_t maximumInstances{1'000'000};
    std::size_t maximumImages{100'000};
    std::size_t maximumImageBytes{1ULL * 1024ULL * 1024ULL * 1024ULL};
    std::uint64_t maximumOutputBytes{4ULL * 1024ULL * 1024ULL * 1024ULL - 1ULL};
};

struct GltfExportReport final {
    std::size_t primitives{};
    std::size_t instances{};
    std::size_t vertices{};
    std::size_t triangles{};
    std::size_t materials{};
    std::size_t textures{};
    std::size_t images{};
    std::uint64_t outputBytes{};
};

class GltfExporter final {
  public:
    /// Input: a validated static reconstruction mesh and explicit resource limits.
    /// Output: one deterministic, self-contained glTF 2 GLB published atomically.
    /// Task: preserve indexed geometry, flat world instances, PBR materials, embedded images,
    /// samplers, UV transforms, alpha modes, and optional vertex colors without Blender.
    /// Failure: animation, skins, morph targets, unsupported image encodings, malformed geometry,
    /// singular transforms, allocation overflow, or I/O failure produce structured errors.
    [[nodiscard]] static Result<GltfExportReport> writeGlb(const MeshAsset& asset,
                                                           const std::filesystem::path& destination,
                                                           const GltfExportLimits& limits = {});
};

} // namespace aether::mesh
