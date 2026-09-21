#pragma once

#include <aether/world_gaussian/GaussianLocalUpdate.hpp>

#include <cstddef>
#include <span>
#include <vector>

namespace aether::world_gaussian {

/// Deterministic little-endian sidecar codec for persistent entity ownership of Gaussian order.
/// The sidecar deliberately stores only stable EntityId values; Gaussian geometry remains in its
/// original asset and cardinality must be checked against that asset before use.
class GaussianOwnershipCodec final {
  public:
    static constexpr std::size_t headerBytes = 32;
    static constexpr std::uint32_t schemaVersion = 1;

    [[nodiscard]] static Result<std::vector<std::byte>>
    encode(const GaussianEntityOwnership& ownership);

    [[nodiscard]] static Result<GaussianEntityOwnership>
    decode(std::span<const std::byte> bytes, std::size_t maximumGaussians = 100'000'000);
};

} // namespace aether::world_gaussian
