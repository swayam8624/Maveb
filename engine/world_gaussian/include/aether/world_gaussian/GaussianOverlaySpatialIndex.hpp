#pragma once

#include <aether/gaussian/GaussianAsset.hpp>
#include <aether/world/SelectiveUpdate.hpp>

#include <compare>
#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

namespace aether::world_gaussian {

struct GaussianRelocation final {
    std::size_t gaussianIndex{};
    simd_float3 oldPosition{};
    simd_float3 newPosition{};
};

struct GaussianOverlaySpatialIndexPolicy final {
    std::size_t maximumDeltaEntries{1'000'000};
    double compactionFraction{0.20};
};

struct GaussianOverlaySpatialIndexStatistics final {
    std::size_t primitiveCount{};
    std::size_t baseEntries{};
    std::size_t deltaEntries{};
    std::size_t movedPrimitives{};
    std::size_t lowerBoundStorageBytes{};
    bool compactionRecommended{};
};

struct GaussianOverlayRegionQueryStatistics final {
    std::size_t baseEntriesVisited{};
    std::size_t staleBaseEntriesSkipped{};
    std::size_t deltaEntriesVisited{};
    std::size_t currentIndicesAppended{};
};

/// Compact exact spatial index for revision-local Gaussian updates.
///
/// The immutable base stores one RegionKey/index pair per primitive in sorted order. Relocations are
/// accumulated transactionally in two compact sorted delta views: one ordered by primitive index for
/// update/consistency checks and one ordered by RegionKey for sparse lookup. A bitset suppresses stale
/// base entries. This avoids rebuilding the million-entry base after every small world revision while
/// keeping queries exact.
///
/// This v0 production probe intentionally supports same-cardinality relocation only. Birth/death and
/// densification/pruning must either compact/rebuild from the authoritative GaussianAsset or use a
/// future explicitly versioned extension; they never silently mutate cardinality here.
class GaussianOverlaySpatialIndex final {
  public:
    [[nodiscard]] static Result<GaussianOverlaySpatialIndex>
    build(const gaussian::GaussianAsset& asset, float cellSizeMeters,
          GaussianOverlaySpatialIndexPolicy policy = {});

    /// Replaces the base with the authoritative current asset and clears all delta state.
    [[nodiscard]] Result<void> compact(const gaussian::GaussianAsset& asset);

    /// Applies one revision's relocations atomically.
    ///
    /// Every oldPosition is checked against the index's current state before mutation. Duplicate
    /// primitive indices, stale old positions, invalid coordinates, or delta-budget overflow reject
    /// the whole batch and leave the index untouched.
    [[nodiscard]] Result<void> applyRelocations(std::span<const GaussianRelocation> relocations);

    /// Appends the exact current primitive indices occupying one region.
    ///
    /// The caller owns output storage so repeated dirty-region queries do not require hidden
    /// per-region allocations. maximumOutputSize is a hard fail-closed bound on total output size.
    [[nodiscard]] Result<GaussianOverlayRegionQueryStatistics>
    appendIndices(world::RegionKey key, std::vector<std::size_t>& output,
                  std::size_t maximumOutputSize) const;

    [[nodiscard]] float cellSizeMeters() const noexcept { return cellSizeMeters_; }
    [[nodiscard]] std::size_t primitiveCount() const noexcept { return primitiveCount_; }
    [[nodiscard]] GaussianOverlaySpatialIndexStatistics statistics() const noexcept;

  private:
    struct Entry final {
        world::RegionKey key{};
        std::uint32_t gaussianIndex{};

        auto operator<=>(const Entry&) const = default;
    };

    struct DeltaByIndex final {
        std::uint32_t gaussianIndex{};
        world::RegionKey key{};

        auto operator<=>(const DeltaByIndex&) const = default;
    };

    explicit GaussianOverlaySpatialIndex(float cellSizeMeters,
                                         GaussianOverlaySpatialIndexPolicy policy)
        : cellSizeMeters_(cellSizeMeters), policy_(policy) {}

    [[nodiscard]] Result<world::RegionKey> regionKey(simd_float3 position) const;
    [[nodiscard]] bool baseContains(world::RegionKey key, std::uint32_t gaussianIndex) const noexcept;
    [[nodiscard]] bool moved(std::uint32_t gaussianIndex) const noexcept;
    void setMoved(std::uint32_t gaussianIndex) noexcept;

    float cellSizeMeters_{};
    GaussianOverlaySpatialIndexPolicy policy_{};
    std::size_t primitiveCount_{};
    std::vector<Entry> baseByRegion_;
    std::vector<DeltaByIndex> deltaByIndex_;
    std::vector<Entry> deltaByRegion_;
    std::vector<std::uint64_t> movedBits_;
};

} // namespace aether::world_gaussian
