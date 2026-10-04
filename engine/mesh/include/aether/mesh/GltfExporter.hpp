#pragma once

#include <aether/core/Error.hpp>
#include <aether/mesh/MeshAsset.hpp>

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <vector>

namespace aether::mesh {

struct GltfExportLimits final {
    std::uint64_t maximumOutputBytes{1ULL * 1024ULL * 1024ULL * 1024ULL};
    std::size_t maximumPrimitives{1'000'000};
    std::size_t maximumInstances{1'000'000};
    std::size_t maximumMaterials{1'000'000};
    std::size_t maximumTextures{1'000'000};
    std::size_t maximumVertices{50'000'000};
    std::size_t maximumIndices{150'000'000};
    std::size_t maximumImages{100'000};
    std::size_t maximumImageBytes{1ULL * 1024ULL * 1024ULL * 1024ULL};
    std::size_t maximumNameBytes{4096};
    std::size_t maximumTotalNameBytes{64ULL * 1024ULL * 1024ULL};
};

class GltfExporter final {
  public:
    /// Input: a validated static mesh asset in glTF's right-handed, Y-up metre frame.
    /// Output: deterministic, self-contained glTF 2 GLB bytes with embedded PNG/JPEG images.
    /// Task: author canonical reconstruction surfaces without a Blender conversion dependency.
    /// Failure: rejects unbounded, malformed, skinned, animated, or morph-target content rather
    /// than silently dropping data; those non-canonical profiles require a future exporter mode.
    [[nodiscard]] static Result<std::vector<std::byte>>
    encodeStatic(const MeshAsset& asset, const GltfExportLimits& limits = {});

    /// Input: the same static asset plus a `.glb` destination.
    /// Output: an atomically replaced self-contained GLB file.
    /// Task: keep partial files out of reconstruction exports when validation or I/O fails.
    [[nodiscard]] static Result<void> writeStatic(const MeshAsset& asset,
                                                  const std::filesystem::path& destination,
                                                  const GltfExportLimits& limits = {});
};

} // namespace aether::mesh
