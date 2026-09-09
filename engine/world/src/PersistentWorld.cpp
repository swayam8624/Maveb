#include <aether/world/PersistentWorld.hpp>

#include <algorithm>
#include <cmath>
#include <limits>
#include <unordered_map>
#include <unordered_set>

namespace aether::world {
namespace {

[[nodiscard]] bool finiteFloat(float value) noexcept {
    return std::isfinite(value);
}

[[nodiscard]] bool finiteVector(simd_float3 value) noexcept {
    return finiteFloat(value.x) && finiteFloat(value.y) && finiteFloat(value.z);
}

[[nodiscard]] bool validBounds(const Bounds& bounds) noexcept {
    return finiteVector(bounds.minimum) && finiteVector(bounds.maximum) &&
           bounds.minimum.x <= bounds.maximum.x && bounds.minimum.y <= bounds.maximum.y &&
           bounds.minimum.z <= bounds.maximum.z;
}

[[nodiscard]] bool validPolicy(const DiffPolicy& policy) noexcept {
    return finiteFloat(policy.translationMeters) && policy.translationMeters >= 0.0F &&
           finiteFloat(policy.rotationRadians) && policy.rotationRadians >= 0.0F &&
           finiteFloat(policy.relativeScale) && policy.relativeScale >= 0.0F &&
           finiteFloat(policy.boundsMeters) && policy.boundsMeters >= 0.0F &&
           finiteFloat(policy.confidenceDelta) && policy.confidenceDelta >= 0.0F;
}

[[nodiscard]] float quaternionAngle(const simd_quatf& lhs, const simd_quatf& rhs) noexcept {
    const simd_float4 lhsVector = lhs.vector;
    const simd_float4 rhsVector = rhs.vector;
    const float lhsLength = simd_length(lhsVector);
    const float rhsLength = simd_length(rhsVector);
    if (lhsLength <= std::numeric_limits<float>::epsilon() ||
        rhsLength <= std::numeric_limits<float>::epsilon()) {
        return std::numeric_limits<float>::infinity();
    }
    const float cosine = std::clamp(std::abs(simd_dot(lhsVector / lhsLength, rhsVector / rhsLength)),
                                    0.0F, 1.0F);
    return 2.0F * std::acos(cosine);
}

[[nodiscard]] float relativeScaleDelta(simd_float3 lhs, simd_float3 rhs) noexcept {
    float maximum{};
    for (std::size_t axis = 0; axis < 3; ++axis) {
        const float denominator =
            std::max({std::abs(lhs[axis]), std::abs(rhs[axis]), 1.0e-6F});
        maximum = std::max(maximum, std::abs(lhs[axis] - rhs[axis]) / denominator);
    }
    return maximum;
}

[[nodiscard]] float boundsDelta(const Bounds& lhs, const Bounds& rhs) noexcept {
    float maximum{};
    for (std::size_t axis = 0; axis < 3; ++axis) {
        maximum = std::max(maximum, std::abs(lhs.minimum[axis] - rhs.minimum[axis]));
        maximum = std::max(maximum, std::abs(lhs.maximum[axis] - rhs.maximum[axis]));
    }
    return maximum;
}

[[nodiscard]] EntityDelta compareEntity(const EntityState& before, const EntityState& after,
                                        const DiffPolicy& policy) noexcept {
    EntityDelta delta;
    delta.id = before.id;
    delta.translationMeters = simd_distance(before.transform.translation, after.transform.translation);
    delta.rotationRadians = quaternionAngle(before.transform.rotation, after.transform.rotation);
    delta.relativeScale = relativeScaleDelta(before.transform.scale, after.transform.scale);
    delta.boundsMeters = boundsDelta(before.worldBounds, after.worldBounds);
    delta.confidenceDelta = std::abs(before.confidence - after.confidence);

    if (delta.translationMeters > policy.translationMeters)
        delta.flags |= ChangeFlag::translated;
    if (delta.rotationRadians > policy.rotationRadians)
        delta.flags |= ChangeFlag::rotated;
    if (delta.relativeScale > policy.relativeScale)
        delta.flags |= ChangeFlag::scaled;
    if (delta.boundsMeters > policy.boundsMeters)
        delta.flags |= ChangeFlag::bounds;
    if (delta.confidenceDelta > policy.confidenceDelta)
        delta.flags |= ChangeFlag::confidence;
    if (before.geometrySignature != after.geometrySignature)
        delta.flags |= ChangeFlag::geometry;
    if (before.appearanceSignature != after.appearanceSignature)
        delta.flags |= ChangeFlag::appearance;
    if (before.semanticLabel != after.semanticLabel)
        delta.flags |= ChangeFlag::semantic;
    if (before.representation != after.representation)
        delta.flags |= ChangeFlag::representation;
    if (before.name != after.name)
        delta.flags |= ChangeFlag::metadata;

    return delta;
}

} // namespace

Result<void> validateSnapshot(const WorldSnapshot& snapshot) {
    std::unordered_set<std::uint64_t> ids;
    ids.reserve(snapshot.entities.size());

    for (const EntityState& entity : snapshot.entities) {
        if (!entity.id.valid())
            return fail(ErrorCode::invalidArgument, "Persistent world entity ID cannot be zero");
        if (!ids.insert(entity.id.value).second) {
            return fail(ErrorCode::invalidArgument, "Persistent world snapshot contains duplicate ID",
                        std::to_string(entity.id.value));
        }
        if (!scene::isFinite(entity.transform) || !scene::hasNonZeroScale(entity.transform)) {
            return fail(ErrorCode::invalidArgument, "Persistent world entity transform is invalid",
                        std::to_string(entity.id.value));
        }
        if (!validBounds(entity.worldBounds)) {
            return fail(ErrorCode::invalidArgument, "Persistent world entity bounds are invalid",
                        std::to_string(entity.id.value));
        }
        if (!finiteFloat(entity.confidence) || entity.confidence < 0.0F ||
            entity.confidence > 1.0F) {
            return fail(ErrorCode::invalidArgument,
                        "Persistent world entity confidence must be finite and in [0, 1]",
                        std::to_string(entity.id.value));
        }
        if (entity.lastObserved > snapshot.timestamp) {
            return fail(ErrorCode::invalidArgument,
                        "Entity observation timestamp cannot be newer than its world snapshot",
                        std::to_string(entity.id.value));
        }
    }
    return {};
}

Result<WorldDiff> diffSnapshots(const WorldSnapshot& before, const WorldSnapshot& after,
                                DiffPolicy policy) {
    if (!validPolicy(policy))
        return fail(ErrorCode::invalidArgument, "Reality Diff thresholds must be finite and non-negative");
    if (auto result = validateSnapshot(before); !result)
        return std::unexpected(result.error());
    if (auto result = validateSnapshot(after); !result)
        return std::unexpected(result.error());
    if (after.timestamp < before.timestamp) {
        return fail(ErrorCode::invalidArgument,
                    "Reality Diff requires the after snapshot to be no older than the before snapshot");
    }

    std::unordered_map<std::uint64_t, const EntityState*> beforeById;
    std::unordered_map<std::uint64_t, const EntityState*> afterById;
    beforeById.reserve(before.entities.size());
    afterById.reserve(after.entities.size());

    std::vector<std::uint64_t> ids;
    ids.reserve(before.entities.size() + after.entities.size());
    for (const EntityState& entity : before.entities) {
        beforeById.emplace(entity.id.value, &entity);
        ids.push_back(entity.id.value);
    }
    for (const EntityState& entity : after.entities) {
        afterById.emplace(entity.id.value, &entity);
        ids.push_back(entity.id.value);
    }
    std::sort(ids.begin(), ids.end());
    ids.erase(std::unique(ids.begin(), ids.end()), ids.end());

    WorldDiff result;
    result.beforeRevision = before.revision;
    result.afterRevision = after.revision;
    result.beforeTimestamp = before.timestamp;
    result.afterTimestamp = after.timestamp;
    result.entities.reserve(ids.size());

    for (const std::uint64_t id : ids) {
        const auto beforeIt = beforeById.find(id);
        const auto afterIt = afterById.find(id);
        if (beforeIt == beforeById.end()) {
            result.entities.push_back(EntityDelta{EntityId{id}, ChangeFlag::added});
            ++result.summary.added;
            continue;
        }
        if (afterIt == afterById.end()) {
            result.entities.push_back(EntityDelta{EntityId{id}, ChangeFlag::removed});
            ++result.summary.removed;
            continue;
        }

        EntityDelta delta = compareEntity(*beforeIt->second, *afterIt->second, policy);
        if (delta.flags == ChangeFlag::none)
            ++result.summary.unchanged;
        else
            ++result.summary.modified;
        result.entities.push_back(delta);
    }

    if (!result.entities.empty()) {
        const std::size_t changed =
            result.summary.added + result.summary.removed + result.summary.modified;
        result.summary.changeRatio = static_cast<float>(changed) /
                                     static_cast<float>(result.entities.size());
    }
    return result;
}

Result<std::uint64_t> WorldTimeline::append(WorldSnapshot snapshot) {
    if (auto result = validateSnapshot(snapshot); !result)
        return std::unexpected(result.error());
    if (!snapshots_.empty() && snapshot.timestamp <= snapshots_.back().timestamp) {
        return fail(ErrorCode::invalidArgument,
                    "Persistent world snapshots must be appended in strictly increasing time");
    }

    snapshot.revision = snapshots_.empty() ? 1U : snapshots_.back().revision + 1U;
    snapshots_.push_back(std::move(snapshot));
    return snapshots_.back().revision;
}

Result<const WorldSnapshot*> WorldTimeline::snapshot(std::uint64_t revision) const {
    if (revision == 0)
        return fail(ErrorCode::invalidArgument, "Persistent world revision cannot be zero");
    const auto match = std::find_if(snapshots_.begin(), snapshots_.end(),
                                    [revision](const WorldSnapshot& candidate) {
                                        return candidate.revision == revision;
                                    });
    if (match == snapshots_.end())
        return fail(ErrorCode::notFound, "Persistent world revision was not found",
                    std::to_string(revision));
    return &*match;
}

Result<WorldDiff> WorldTimeline::diff(std::uint64_t beforeRevision, std::uint64_t afterRevision,
                                      DiffPolicy policy) const {
    auto before = snapshot(beforeRevision);
    if (!before)
        return std::unexpected(before.error());
    auto after = snapshot(afterRevision);
    if (!after)
        return std::unexpected(after.error());
    if (beforeRevision >= afterRevision) {
        return fail(ErrorCode::invalidArgument,
                    "Reality Diff requires an earlier revision followed by a later revision");
    }
    return diffSnapshots(**before, **after, policy);
}

Result<WorldDiff> WorldTimeline::latestDiff(DiffPolicy policy) const {
    if (snapshots_.size() < 2)
        return fail(ErrorCode::notFound, "Reality Diff requires at least two world revisions");
    return diffSnapshots(snapshots_[snapshots_.size() - 2], snapshots_.back(), policy);
}

} // namespace aether::world
