#pragma once

#include <aether/gaussian/GaussianAsset.hpp>
#include <aether/world/SelectiveUpdate.hpp>

#include <cstddef>
#include <span>
#include <unordered_map>
#include <vector>

namespace aether::world_gaussian {

/// Persistent spatial lookup for Gaussian primitive indices keyed by the same
/// metric RegionKey used by the World selective-update contract.
///
/// Callers that mutate Gaussian positions must route cell-crossing moves through
/// relocateGaussian() or rebuild() before issuing indexed selections.
class GaussianSpatialIndex final {
  public:
    struct Statistics final {
        std::size_t primitiveCount{};
        std::size_t occupiedRegions{};
        std::size_t storedIndexEntries{};
    };

    static Result<GaussianSpatialIndex> build(const gaussian::GaussianAsset& asset,
                                              float cellSizeMeters);
    Result<void> rebuild(const gaussian::GaussianAsset& asset);
    Result<void> relocateGaussian(std::size_t gaussianIndex, simd_float3 oldPosition,
                                  simd_float3 newPosition);

    [[nodiscard]] std::span<const std::size_t> indices(world::RegionKey key) const noexcept;
    [[nodiscard]] float cellSizeMeters() const noexcept {
        return cellSizeMeters_;
    }
    [[nodiscard]] std::size_t primitiveCount() const noexcept {
        return primitiveCount_;
    }
    [[nodiscard]] Statistics statistics() const noexcept;

  private:
    struct RegionKeyHash final {
        [[nodiscard]] std::size_t operator()(const world::RegionKey& key) const noexcept;
    };

    explicit GaussianSpatialIndex(float cellSizeMeters) : cellSizeMeters_(cellSizeMeters) {}
    [[nodiscard]] Result<world::RegionKey> regionKey(simd_float3 position) const;

    float cellSizeMeters_{};
    std::size_t primitiveCount_{};
    std::unordered_map<world::RegionKey, std::vector<std::size_t>, RegionKeyHash> buckets_;
};

} // namespace aether::world_gaussian
