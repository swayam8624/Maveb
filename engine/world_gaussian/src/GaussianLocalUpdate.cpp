#include <aether/world_gaussian/GaussianLocalUpdate.hpp>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace aether::world_gaussian {
namespace {

struct RegionKeyHash final {
    [[nodiscard]] std::size_t operator()(const world::RegionKey& key) const noexcept {
        std::size_t seed = std::hash<std::int32_t>{}(key.x);
        const auto combine = [&seed](std::int32_t value) {
            const std::size_t hashed = std::hash<std::int32_t>{}(value);
            seed ^= hashed + static_cast<std::size_t>(0x9e3779b97f4a7c15ULL) + (seed << 6U) +
                    (seed >> 2U);
        };
        combine(key.y);
        combine(key.z);
        return seed;
    }
};

struct DirtyRegionInfo final {
    std::unordered_set<std::uint64_t> entityIds;
};

[[nodiscard]] Result<std::int32_t> cellCoordinate(float value, float cellSizeMeters) {
    if (!std::isfinite(value))
        return fail(ErrorCode::corruptData, "Gaussian position contains a non-finite coordinate");
    const double scaled =
        std::floor(static_cast<double>(value) / static_cast<double>(cellSizeMeters));
    constexpr double minimum = static_cast<double>(std::numeric_limits<std::int32_t>::min());
    constexpr double maximum = static_cast<double>(std::numeric_limits<std::int32_t>::max());
    if (scaled < minimum || scaled > maximum)
        return fail(ErrorCode::resourceExhausted, "Gaussian position exceeds dirty-grid range");
    return static_cast<std::int32_t>(scaled);
}

[[nodiscard]] Result<world::RegionKey>
regionKey(const gaussian::Gaussian& gaussian, float cellSizeMeters) {
    auto x = cellCoordinate(gaussian.position[0], cellSizeMeters);
    auto y = cellCoordinate(gaussian.position[1], cellSizeMeters);
    auto z = cellCoordinate(gaussian.position[2], cellSizeMeters);
    if (!x)
        return std::unexpected(x.error());
    if (!y)
        return std::unexpected(y.error());
    if (!z)
        return std::unexpected(z.error());
    return world::RegionKey{*x, *y, *z};
}

[[nodiscard]] bool finiteDelta(simd_float3 delta) noexcept {
    return std::isfinite(delta.x) && std::isfinite(delta.y) && std::isfinite(delta.z);
}

[[nodiscard]] bool finiteTranslatedPosition(const gaussian::Gaussian& primitive,
                                            simd_float3 delta) noexcept {
    return std::isfinite(primitive.position[0] + delta.x) &&
           std::isfinite(primitive.position[1] + delta.y) &&
           std::isfinite(primitive.position[2] + delta.z);
}

[[nodiscard]] Result<std::vector<std::size_t>>
preflightOwnedTranslation(const gaussian::GaussianAsset& asset,
                          const GaussianEntityOwnership& ownership, world::EntityId entity,
                          simd_float3 translationDelta, std::size_t maximumAffectedGaussians) {
    if (!entity.valid())
        return fail(ErrorCode::invalidArgument, "Gaussian translation entity ID cannot be zero");
    if (!finiteDelta(translationDelta))
        return fail(ErrorCode::invalidArgument, "Gaussian translation delta must be finite");
    if (maximumAffectedGaussians == 0)
        return fail(ErrorCode::invalidArgument, "Gaussian translation budget cannot be zero");
    if (ownership.owners.size() != asset.gaussians.size()) {
        return fail(ErrorCode::invalidArgument,
                    "Gaussian ownership count must match Gaussian asset primitive count");
    }

    std::vector<std::size_t> affectedIndices;
    affectedIndices.reserve(std::min(asset.gaussians.size(), maximumAffectedGaussians));
    for (std::size_t index = 0; index < asset.gaussians.size(); ++index) {
        if (ownership.owners[index] != entity)
            continue;
        if (affectedIndices.size() >= maximumAffectedGaussians) {
            return fail(ErrorCode::resourceExhausted,
                        "Gaussian entity translation exceeds affected-primitive budget");
        }
        if (!finiteTranslatedPosition(asset.gaussians[index], translationDelta)) {
            return fail(ErrorCode::resourceExhausted,
                        "Gaussian entity translation would produce a non-finite position");
        }
        affectedIndices.push_back(index);
    }
    return affectedIndices;
}

void applyOwnedTranslation(gaussian::GaussianAsset& asset,
                           const std::vector<std::size_t>& affectedIndices,
                           simd_float3 translationDelta) noexcept {
    for (const std::size_t index : affectedIndices) {
        gaussian::Gaussian& primitive = asset.gaussians[index];
        primitive.position[0] += translationDelta.x;
        primitive.position[1] += translationDelta.y;
        primitive.position[2] += translationDelta.z;
    }
}

[[nodiscard]] const world::EntityState*
findEntity(const world::WorldSnapshot& snapshot, world::EntityId entity) noexcept {
    const auto match = std::find_if(snapshot.entities.begin(), snapshot.entities.end(),
                                    [entity](const world::EntityState& state) {
                                        return state.id == entity;
                                    });
    return match == snapshot.entities.end() ? nullptr : &*match;
}

} // namespace

Result<GaussianLocalUpdateSelection>
selectGaussiansForLocalUpdate(const gaussian::GaussianAsset& asset,
                              const world::SelectiveUpdatePlan& worldUpdate,
                              const GaussianEntityOwnership* ownership,
                              GaussianLocalUpdatePolicy policy) {
    if (!std::isfinite(worldUpdate.cellSizeMeters) || worldUpdate.cellSizeMeters <= 0.0F)
        return fail(ErrorCode::invalidArgument, "World update cell size must be finite and positive");
    if (policy.maximumAffectedGaussians == 0)
        return fail(ErrorCode::invalidArgument, "Gaussian local-update budget cannot be zero");
    if (ownership && ownership->owners.size() != asset.gaussians.size()) {
        return fail(ErrorCode::invalidArgument,
                    "Gaussian ownership count must match Gaussian asset primitive count");
    }

    std::unordered_map<world::RegionKey, DirtyRegionInfo, RegionKeyHash> dirty;
    dirty.reserve(worldUpdate.dirtyRegions.size());
    for (const world::RegionUpdate& region : worldUpdate.dirtyRegions) {
        DirtyRegionInfo& info = dirty[region.key];
        for (const world::EntityId entity : region.entities) {
            if (entity.valid())
                info.entityIds.insert(entity.value);
        }
    }

    GaussianLocalUpdateSelection result;
    result.gaussianIndices.reserve(
        std::min(asset.gaussians.size(), policy.maximumAffectedGaussians));

    for (std::size_t index = 0; index < asset.gaussians.size(); ++index) {
        auto key = regionKey(asset.gaussians[index], worldUpdate.cellSizeMeters);
        if (!key)
            return std::unexpected(key.error());
        const auto region = dirty.find(*key);
        if (region == dirty.end()) {
            ++result.unaffectedGaussians;
            continue;
        }

        bool select = ownership == nullptr;
        if (ownership) {
            const world::EntityId owner = ownership->owners[index];
            if (!owner.valid()) {
                select = policy.includeUnownedGaussians;
                if (select)
                    ++result.conservativeUnownedMatches;
            } else if (region->second.entityIds.contains(owner.value)) {
                select = true;
                ++result.ownedMatches;
            } else {
                ++result.rejectedStableOwnedGaussians;
            }
        }

        if (!select) {
            ++result.unaffectedGaussians;
            continue;
        }
        if (result.gaussianIndices.size() >= policy.maximumAffectedGaussians) {
            return fail(ErrorCode::resourceExhausted,
                        "Gaussian local update exceeds affected-primitive budget");
        }
        result.gaussianIndices.push_back(index);
    }
    return result;
}

Result<std::size_t>
translateOwnedGaussians(gaussian::GaussianAsset& asset, const GaussianEntityOwnership& ownership,
                        world::EntityId entity, simd_float3 translationDelta,
                        std::size_t maximumAffectedGaussians) {
    auto affected = preflightOwnedTranslation(asset, ownership, entity, translationDelta,
                                              maximumAffectedGaussians);
    if (!affected)
        return std::unexpected(affected.error());
    applyOwnedTranslation(asset, *affected, translationDelta);
    return affected->size();
}

Result<PersistentGaussianTranslationResult>
translatePersistentGaussianEntity(world::PersistentWorldModel& worldModel,
                                  gaussian::GaussianAsset& asset,
                                  const GaussianEntityOwnership& ownership,
                                  world::EntityId entity, simd_float3 targetWorldTranslation,
                                  world::TimestampNs timestamp, world::WorldEditPolicy worldPolicy,
                                  GaussianLocalUpdatePolicy gaussianPolicy) {
    const world::WorldSnapshot* latest = worldModel.latest();
    if (!latest)
        return fail(ErrorCode::notFound, "Persistent Gaussian edit requires an existing world");
    const world::EntityState* state = findEntity(*latest, entity);
    if (!state)
        return fail(ErrorCode::notFound, "Persistent Gaussian entity was not found",
                    std::to_string(entity.value));
    if (!finiteDelta(targetWorldTranslation))
        return fail(ErrorCode::invalidArgument, "Gaussian target translation must be finite");

    const simd_float3 translationDelta = targetWorldTranslation - state->transform.translation;
    world::EntityPatch patch;
    patch.id = entity;
    patch.transform = state->transform;
    patch.transform->translation = targetWorldTranslation;

    auto preparedWorld = world::prepareWorldEdit(*latest, timestamp, {patch}, worldPolicy);
    if (!preparedWorld)
        return std::unexpected(preparedWorld.error());

    auto affected = preflightOwnedTranslation(asset, ownership, entity, translationDelta,
                                              gaussianPolicy.maximumAffectedGaussians);
    if (!affected)
        return std::unexpected(affected.error());

    auto selection = selectGaussiansForLocalUpdate(asset, preparedWorld->selectiveUpdate, &ownership,
                                                   gaussianPolicy);
    if (!selection)
        return std::unexpected(selection.error());

    auto committedWorld = worldModel.edit(timestamp, {patch}, worldPolicy);
    if (!committedWorld)
        return std::unexpected(committedWorld.error());

    applyOwnedTranslation(asset, *affected, translationDelta);
    return PersistentGaussianTranslationResult{
        .worldEdit = std::move(*committedWorld),
        .translatedGaussians = affected->size(),
        .reoptimizationSelection = std::move(*selection),
    };
}

} // namespace aether::world_gaussian
