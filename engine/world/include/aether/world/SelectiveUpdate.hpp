#pragma once

#include <aether/world/PersistentWorld.hpp>

#include <compare>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace aether::world {

/// Integer coordinate of a metric persistent-world update cell.
struct RegionKey final {
    std::int32_t x{};
    std::int32_t y{};
    std::int32_t z{};

    auto operator<=>(const RegionKey&) const = default;
};

/// Controls how Reality Diff is converted into bounded reconstruction work.
struct SelectiveUpdatePolicy final {
    float cellSizeMeters{0.5F};
    std::uint32_t haloCells{1};
    std::size_t maximumDirtyRegions{262144};
    bool appearanceChangesRequireUpdate{true};
    bool confidenceChangesRequireUpdate{false};
    bool semanticChangesRequireUpdate{false};
};

/// One spatial region that must be reconsidered by downstream reconstruction/representation layers.
struct RegionUpdate final {
    RegionKey key{};
    Bounds worldBounds;
    ChangeFlag causes{ChangeFlag::none};
    std::vector<EntityId> entities;
};

struct SelectiveUpdatePlan final {
    float cellSizeMeters{};
    std::uint32_t haloCells{};
    std::vector<RegionUpdate> dirtyRegions;
    std::size_t unchangedEntities{};
    std::size_t changedEntities{};
};

/// Converts an entity-level Reality Diff into a deterministic, halo-expanded set of metric cells.
///
/// Added entities dirty their new bounds, removed entities dirty their previous bounds, and moved
/// or modified entities dirty the union of old and new bounds. The result is deliberately
/// independent of TSDF/Gaussian implementation details so both representations can consume the same
/// local-update contract.
[[nodiscard]] Result<SelectiveUpdatePlan> planSelectiveUpdates(const WorldSnapshot& before,
                                                               const WorldSnapshot& after,
                                                               const WorldDiff& diff,
                                                               SelectiveUpdatePolicy policy = {});

} // namespace aether::world
