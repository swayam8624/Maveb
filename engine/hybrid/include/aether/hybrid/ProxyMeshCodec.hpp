#pragma once

#include <aether/core/Error.hpp>
#include <aether/hybrid/ProxyMesh.hpp>

#include <cstddef>
#include <span>
#include <vector>

namespace aether::hybrid {

class ProxyMeshCodec final {
  public:
    static constexpr std::size_t headerBytes = 32;
    static constexpr std::size_t vertexBytes = 32;

    /// Input: validated triangle proxy geometry in AETHER coordinates.
    /// Output: deterministic little-endian proxy-mesh chunk v1 bytes.
    /// Task: keep package geometry independent of compiler and Metal ABI layouts.
    [[nodiscard]] static Result<std::vector<std::byte>> encode(const ProxyMesh& mesh);

    /// Input: untrusted canonical proxy bytes and explicit allocation limits.
    /// Output: finite, normalized, indexed triangle geometry.
    /// Task: reject malformed package data before GPU allocation.
    [[nodiscard]] static Result<ProxyMesh> decode(std::span<const std::byte> bytes,
                                                  std::size_t maximumVertices = 50'000'000,
                                                  std::size_t maximumTriangles = 100'000'000);
};

} // namespace aether::hybrid
