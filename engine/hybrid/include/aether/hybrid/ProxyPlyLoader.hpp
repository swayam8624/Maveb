#pragma once

#include <aether/core/Error.hpp>
#include <aether/hybrid/ProxyMesh.hpp>

#include <cstddef>
#include <cstdint>
#include <filesystem>

namespace aether::hybrid {

struct ProxyPlyLimits final {
    std::uintmax_t maximumFileBytes{8ULL * 1024ULL * 1024ULL * 1024ULL};
    std::size_t maximumHeaderBytes{1ULL * 1024ULL * 1024ULL};
    std::size_t maximumVertices{50'000'000};
    std::size_t maximumTriangles{100'000'000};
    std::size_t maximumVertexProperties{64};
};

class ProxyPlyLoader final {
  public:
    /// Input: Open3D-style ASCII or binary-little-endian triangle PLY.
    /// Output: bounded canonical proxy vertices and uint32 triangle indices.
    /// Task: validate reconstruction output before packaging or rendering.
    [[nodiscard]] static Result<ProxyMesh> load(const std::filesystem::path& path,
                                                const ProxyPlyLimits& limits = {});
};

} // namespace aether::hybrid
