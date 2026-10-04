#pragma once

#include <aether/core/Error.hpp>
#include <aether/gaussian/GaussianAsset.hpp>

#include <cstddef>
#include <span>
#include <vector>

namespace aether::gaussian {

class GaussianCodec final {
  public:
    static constexpr std::size_t headerBytes = 32;
    static constexpr std::size_t recordBytes = 256;

    /// Input: validated canonical Gaussians.
    /// Output: deterministic little-endian base-Gaussian chunk v1 bytes.
    /// Task: provide a compiler/ABI-independent package and streaming representation.
    [[nodiscard]] static Result<std::vector<std::byte>> encode(const GaussianAsset& asset);

    /// Input: untrusted base-Gaussian chunk bytes and an explicit record limit.
    /// Output: fully validated canonical Gaussians.
    /// Task: prevent raw C++ layouts or malformed package payloads from crossing into rendering.
    [[nodiscard]] static Result<GaussianAsset> decode(std::span<const std::byte> bytes,
                                                      std::size_t maximumGaussians = 100'000'000);
};

} // namespace aether::gaussian
