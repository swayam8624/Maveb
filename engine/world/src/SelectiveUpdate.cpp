#include <aether/world/SelectiveUpdate.hpp>

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <unordered_map>

namespace aether::world {
namespace {

[[nodiscard]] bool validPolicy(const SelectiveUpdatePolicy& policy) noexcept {
    return std::isfinite(policy.cellSizeMeters) && policy.cellSizeMeters > 0.0F &&
           policy.maximumDirtyRegions > 0;
}

[[nodiscard]] bool any(ChangeFlag value, ChangeFlag flags) noexcept {
    return (static_cast<std::uint16_t>(value) & static_cast<std::uint16_t>(flags)) != 0;
}

[[nodiscard]] bool requiresSpatialUpdate(ChangeFlag flags,
                                         const SelectiveUpdatePolicy& policy) noexcept {
    constexpr ChangeFlag structural =
        ChangeFlag::added | ChangeFlag::removed | ChangeFlag::translated | ChangeFlag::rotated |
        ChangeFlag::scaled | ChangeFlag::geometry | ChangeFlag::representation | ChangeFlag::bounds;
    if (any(flags, structural))
        return true;
    if (policy.appearanceChangesRequireUpdate && hasFlag(flags, ChangeFlag::appearance))
        return true;
    if (policy.confidenceChangesRequireUpdate && hasFlag(flags, ChangeFlag::confidence))
        return true;
    if (policy.semanticChangesRequireUpdate && hasFlag(flags, ChangeFlag::semantic))
        return true;
    return false;
}

[[nodiscard]] Bounds mergedBounds(const Bounds& lhs, const Bounds& rhs) noexcept {
    return Bounds{{std::min(lhs.minimum.x, rhs.minimum.x), std::min(lhs.minimum.y, rhs.minimum.y),
                   std::min(lhs.minimum.z, rhs.minimum.z)},
                  {std::max(lhs.maximum.x, rhs.maximum.x), std::max(lhs.maximum.y, rhs.maximum.y),
                   std::max(lhs.maximum.z, rhs.maximum.z)}};
}

[[nodiscard]] Bounds regionBounds(RegionKey key, float cellSizeMeters) noexcept {
    const simd_float3 minimum{static_cast<float>(key.x) * cellSizeMeters,
                              static_cast<float>(key.y) * cellSizeMeters,
                              static_cast<float>(key.z) * cellSizeMeters};
    return Bounds{minimum, minimum + simd_make_float3(cellSizeMeters)};
}

[[nodiscard]] Result<std::int32_t> checkedCellCoordinate(float coordinate, float cellSizeMeters,
                                                          std::int64_t halo) {
    const double cell = std::floor(static_cast<double>(coordinate) /
                                   static_cast<double>(cellSizeMeters));
    const double expanded = cell + static_cast<double>(halo);
    if (expanded < static_cast<double>(std::numeric_limits<std::int32_t>::min()) ||
        expanded > static_cast<double>(std::numeric_limits<std::int32_t>::max())) {
        return fail(ErrorCode::resourceExhausted, "Selective update grid coordinate exceeds int32");
    }
    return static_cast<std::int32_t>(expanded);
}

[[nodiscard]] const EntityState*
findEntity(const std::unordered_map<std::uint64_t, const EntityState*>& entities, EntityId id) {
    const auto match = entities.find(id.value);
    return match == entities.end() ? nullptr : match->second;
}

Result<void> addDirtyBounds(std::map<RegionKey, RegionUpdate>& regions, const Bounds& bounds,
                            EntityId entity, ChangeFlag causes,
                            const SelectiveUpdatePolicy& policy) {
    const std::int64_t halo = static_cast<std::int64_t>(policy.haloCells);
    auto minX = checkedCellCoordinate(bounds.minimum.x, policy.cellSizeMeters, -halo);
    auto minY = checkedCellCoordinate(bounds.minimum.y, policy.cellSizeMeters, -halo);
    auto minZ = checkedCellCoordinate(bounds.minimum.z, policy.cellSizeMeters, -halo);
    auto maxX = checkedCellCoordinate(bounds.maximum.x, policy.cellSizeMeters, halo);
    auto maxY = checkedCellCoordinate(bounds.maximum.y, policy.cellSizeMeters, halo);
    auto maxZ = checkedCellCoordinate(bounds.maximum.z, policy.cellSizeMeters, halo);
    if (!minX)
        return std::unexpected(minX.error());
    if (!minY)
        return std::unexpected(minY.error());
    if (!minZ)
        return std::unexpected(minZ.error());
    if (!maxX)
        return std::unexpected(maxX.error());
    if (!maxY)
        return std::unexpected(maxY.error());
    if (!maxZ)
        return std::unexpected(maxZ.error());

    for (std::int64_t z = *minZ; z <= *maxZ; ++z) {
        for (std::int64_t y = *minY; y <= *maxY; ++y) {
            for (std::int64_t x = *minX; x <= *maxX; ++x) {
                const RegionKey key{static_cast<std::int32_t>(x), static_cast<std::int32_t>(y),
                                    static_cast<std::int32_t>(z)};
                auto match = regions.find(key);
                if (match == regions.end()) {
                    if (regions.size() >= policy.maximumDirtyRegions) {
                        return fail(ErrorCode::resourceExhausted,
                                    "Selective update exceeds configured dirty-region budget");
                    }
                    RegionUpdate update;
                    update.key = key;
                    update.worldBounds = regionBounds(key, policy.cellSizeMeters);
                    update.causes = causes;
                    update.entities.push_back(entity);
                    regions.emplace(key, std::move(update));
                } else {
                    match->second.causes |= causes;
                    if (std::find(match->second.entities.begin(), match->second.entities.end(), entity) ==
                        match->second.entities.end()) {
                        match->second.entities.push_back(entity);
                    }
                }
            }
        }
    }
    return {};
}

} // namespace

Result<SelectiveUpdatePlan> planSelectiveUpdates(const WorldSnapshot& before,
                                                  const WorldSnapshot& after,
                                                  const WorldDiff& diff,
                                                  SelectiveUpdatePolicy policy) {
    if (!validPolicy(policy)) {
        return fail(ErrorCode::invalidArgument,
                    "Selective update policy requires a finite positive cell size and region budget");
    }
    if (auto result = validateSnapshot(before); !result)
        return std::unexpected(result.error());
    if (auto result = validateSnapshot(after); !result)
        return std::unexpected(result.error());
    if ((diff.beforeRevision != 0 && before.revision != diff.beforeRevision) ||
        (diff.afterRevision != 0 && after.revision != diff.afterRevision)) {
        return fail(ErrorCode::invalidArgument,
                    "Reality Diff revisions do not match selective-update snapshots");
    }

    std::unordered_map<std::uint64_t, const EntityState*> beforeById;
    std::unordered_map<std::uint64_t, const EntityState*> afterById;
    beforeById.reserve(before.entities.size());
    afterById.reserve(after.entities.size());
    for (const EntityState& entity : before.entities)
        beforeById.emplace(entity.id.value, &entity);
    for (const EntityState& entity : after.entities)
        afterById.emplace(entity.id.value, &entity);

    std::map<RegionKey, RegionUpdate> dirty;
    SelectiveUpdatePlan plan;
    plan.cellSizeMeters = policy.cellSizeMeters;
    plan.haloCells = policy.haloCells;

    for (const EntityDelta& delta : diff.entities) {
        if (delta.flags == ChangeFlag::none) {
            ++plan.unchangedEntities;
            continue;
        }
        if (!requiresSpatialUpdate(delta.flags, policy)) {
            ++plan.unchangedEntities;
            continue;
        }

        const EntityState* beforeEntity = findEntity(beforeById, delta.id);
        const EntityState* afterEntity = findEntity(afterById, delta.id);
        Bounds affected;
        if (hasFlag(delta.flags, ChangeFlag::added)) {
            if (!afterEntity)
                return fail(ErrorCode::corruptData, "Added Reality Diff entity is missing after state");
            affected = afterEntity->worldBounds;
        } else if (hasFlag(delta.flags, ChangeFlag::removed)) {
            if (!beforeEntity)
                return fail(ErrorCode::corruptData,
                            "Removed Reality Diff entity is missing before state");
            affected = beforeEntity->worldBounds;
        } else {
            if (!beforeEntity || !afterEntity) {
                return fail(ErrorCode::corruptData,
                            "Modified Reality Diff entity is missing temporal state");
            }
            affected = mergedBounds(beforeEntity->worldBounds, afterEntity->worldBounds);
        }

        if (auto result = addDirtyBounds(dirty, affected, delta.id, delta.flags, policy); !result)
            return std::unexpected(result.error());
        ++plan.changedEntities;
    }

    plan.dirtyRegions.reserve(dirty.size());
    for (auto& [key, update] : dirty) {
        static_cast<void>(key);
        std::sort(update.entities.begin(), update.entities.end());
        plan.dirtyRegions.push_back(std::move(update));
    }
    return plan;
}

} // namespace aether::world
