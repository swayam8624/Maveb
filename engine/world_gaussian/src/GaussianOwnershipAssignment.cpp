#include <aether/world_gaussian/GaussianOwnershipAssignment.hpp>

#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>
#include <vector>

namespace aether::world_gaussian {
namespace {

struct EntityCandidate final {
    world::EntityId id{};
    world::Bounds bounds;
    float minimumX{};
    float maximumX{};
    float volume{};
};

struct OwnershipChoice final {
    bool valid{};
    bool containsPoint{};
    float distance{std::numeric_limits<float>::infinity()};
    float volume{std::numeric_limits<float>::infinity()};
    world::EntityId id{};
};

[[nodiscard]] bool finitePoint(const gaussian::Gaussian& primitive) noexcept {
    return std::isfinite(primitive.position[0]) && std::isfinite(primitive.position[1]) &&
           std::isfinite(primitive.position[2]);
}

[[nodiscard]] bool eligibleRepresentation(world::RepresentationKind representation,
                                          bool required) noexcept {
    return !required || representation == world::RepresentationKind::gaussian ||
           representation == world::RepresentationKind::hybrid;
}

[[nodiscard]] float boundsVolume(const world::Bounds& bounds) noexcept {
    const simd_float3 extent =
        simd_max(bounds.maximum - bounds.minimum, simd_float3{0.0F, 0.0F, 0.0F});
    return extent.x * extent.y * extent.z;
}

[[nodiscard]] bool containsPoint(const world::Bounds& bounds, simd_float3 point) noexcept {
    return point.x >= bounds.minimum.x && point.x <= bounds.maximum.x &&
           point.y >= bounds.minimum.y && point.y <= bounds.maximum.y &&
           point.z >= bounds.minimum.z && point.z <= bounds.maximum.z;
}

[[nodiscard]] float pointToBounds(const world::Bounds& bounds, simd_float3 point) noexcept {
    const simd_float3 closest = simd_clamp(point, bounds.minimum, bounds.maximum);
    return simd_distance(point, closest);
}

[[nodiscard]] bool betterChoice(const OwnershipChoice& candidate,
                                const OwnershipChoice& current) noexcept {
    if (!current.valid)
        return true;
    if (candidate.containsPoint != current.containsPoint)
        return candidate.containsPoint;
    if (candidate.containsPoint) {
        if (candidate.volume != current.volume)
            return candidate.volume < current.volume;
        return candidate.id < current.id;
    }
    if (candidate.distance != current.distance)
        return candidate.distance < current.distance;
    if (candidate.volume != current.volume)
        return candidate.volume < current.volume;
    return candidate.id < current.id;
}

} // namespace

Result<GaussianOwnershipAssignmentResult>
assignGaussianOwnership(const gaussian::GaussianAsset& asset, const world::WorldSnapshot& snapshot,
                        GaussianOwnershipAssignmentPolicy policy) {
    if (auto validation = world::validateSnapshot(snapshot); !validation)
        return std::unexpected(validation.error());
    if (!std::isfinite(policy.maximumSurfaceDistanceMeters) ||
        policy.maximumSurfaceDistanceMeters < 0.0F || policy.maximumCandidatePairs == 0) {
        return fail(ErrorCode::invalidArgument,
                    "Gaussian ownership assignment requires finite distance and non-zero budget");
    }

    GaussianOwnershipAssignmentResult result;
    result.ownership.owners.resize(asset.gaussians.size());
    for (const gaussian::Gaussian& primitive : asset.gaussians) {
        if (!finitePoint(primitive))
            return fail(ErrorCode::corruptData,
                        "Gaussian ownership assignment encountered non-finite primitive position");
    }

    std::vector<EntityCandidate> entities;
    entities.reserve(snapshot.entities.size());
    for (const world::EntityState& entity : snapshot.entities) {
        if (!eligibleRepresentation(entity.representation, policy.requireGaussianRepresentation))
            continue;
        entities.push_back(EntityCandidate{
            entity.id,
            entity.worldBounds,
            entity.worldBounds.minimum.x,
            entity.worldBounds.maximum.x,
            boundsVolume(entity.worldBounds),
        });
    }
    std::sort(entities.begin(), entities.end(), [](const EntityCandidate& lhs,
                                                    const EntityCandidate& rhs) {
        if (lhs.minimumX != rhs.minimumX)
            return lhs.minimumX < rhs.minimumX;
        return lhs.id < rhs.id;
    });

    std::vector<std::size_t> gaussianOrder(asset.gaussians.size());
    std::iota(gaussianOrder.begin(), gaussianOrder.end(), 0);
    std::sort(gaussianOrder.begin(), gaussianOrder.end(), [&](std::size_t lhs, std::size_t rhs) {
        const float leftX = asset.gaussians[lhs].position[0];
        const float rightX = asset.gaussians[rhs].position[0];
        if (leftX != rightX)
            return leftX < rightX;
        return lhs < rhs;
    });

    std::vector<std::size_t> active;
    active.reserve(entities.size());
    std::size_t entityCursor{};
    for (const std::size_t gaussianIndex : gaussianOrder) {
        const gaussian::Gaussian& primitive = asset.gaussians[gaussianIndex];
        const simd_float3 point{primitive.position[0], primitive.position[1], primitive.position[2]};
        const float minimumCandidateX = point.x - policy.maximumSurfaceDistanceMeters;
        const float maximumCandidateX = point.x + policy.maximumSurfaceDistanceMeters;

        while (entityCursor < entities.size() &&
               entities[entityCursor].minimumX <= maximumCandidateX) {
            active.push_back(entityCursor++);
        }
        active.erase(std::remove_if(active.begin(), active.end(), [&](std::size_t index) {
                         return entities[index].maximumX < minimumCandidateX;
                     }),
                     active.end());

        OwnershipChoice best;
        for (const std::size_t entityIndex : active) {
            if (++result.candidatePairs > policy.maximumCandidatePairs) {
                return fail(ErrorCode::resourceExhausted,
                            "Gaussian ownership assignment exceeds candidate-pair budget");
            }
            const EntityCandidate& entity = entities[entityIndex];
            const float distance = pointToBounds(entity.bounds, point);
            if (distance > policy.maximumSurfaceDistanceMeters)
                continue;
            OwnershipChoice candidate{
                .valid = true,
                .containsPoint = containsPoint(entity.bounds, point),
                .distance = distance,
                .volume = entity.volume,
                .id = entity.id,
            };
            if (betterChoice(candidate, best))
                best = candidate;
        }

        if (best.valid) {
            result.ownership.owners[gaussianIndex] = best.id;
            ++result.assignedGaussians;
        } else {
            ++result.unassignedGaussians;
        }
    }
    return result;
}

} // namespace aether::world_gaussian
