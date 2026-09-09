#include <aether/world/EntityAssociation.hpp>

#include <algorithm>
#include <cmath>
#include <limits>
#include <unordered_map>
#include <unordered_set>

namespace aether::world {
namespace {

struct Candidate final {
    std::size_t observationIndex{};
    std::size_t previousIndex{};
    float score{};
    float centerDistance{};
    std::uint64_t previousId{};
};

[[nodiscard]] simd_float3 center(const Bounds& bounds) noexcept {
    return (bounds.minimum + bounds.maximum) * 0.5F;
}

[[nodiscard]] float volume(const Bounds& bounds) noexcept {
    const simd_float3 extent = simd_max(bounds.maximum - bounds.minimum, simd_float3{0.0F, 0.0F, 0.0F});
    return extent.x * extent.y * extent.z;
}

[[nodiscard]] float boundsIoU(const Bounds& lhs, const Bounds& rhs) noexcept {
    const Bounds intersection{
        simd_max(lhs.minimum, rhs.minimum),
        simd_min(lhs.maximum, rhs.maximum),
    };
    const float intersectionVolume = volume(intersection);
    const float unionVolume = volume(lhs) + volume(rhs) - intersectionVolume;
    if (unionVolume <= std::numeric_limits<float>::epsilon())
        return 0.0F;
    return std::clamp(intersectionVolume / unionVolume, 0.0F, 1.0F);
}

[[nodiscard]] bool semanticCompatible(const EntityState& previous, const EntityState& observation,
                                      const AssociationPolicy& policy) noexcept {
    if (policy.allowSemanticMismatch || previous.semanticLabel.empty() ||
        observation.semanticLabel.empty()) {
        return true;
    }
    return previous.semanticLabel == observation.semanticLabel;
}

[[nodiscard]] float associationScore(const EntityState& previous, const EntityState& observation,
                                     float centerDistance,
                                     const AssociationPolicy& policy) noexcept {
    const float distanceScore =
        1.0F - std::clamp(centerDistance / policy.maximumCenterDistanceMeters, 0.0F, 1.0F);
    float score = 0.55F * distanceScore + 0.25F * boundsIoU(previous.worldBounds, observation.worldBounds);
    if (!previous.semanticLabel.empty() && previous.semanticLabel == observation.semanticLabel)
        score += 0.15F;
    if (previous.geometrySignature != 0 &&
        previous.geometrySignature == observation.geometrySignature) {
        score += 0.10F;
    }
    if (previous.appearanceSignature != 0 &&
        previous.appearanceSignature == observation.appearanceSignature) {
        score += 0.05F;
    }
    if (previous.representation == observation.representation)
        score += 0.05F;
    return score;
}

[[nodiscard]] Result<void> validateObservationPayload(TimestampNs timestamp,
                                                       const std::vector<EntityState>& observations) {
    WorldSnapshot validation;
    validation.timestamp = timestamp;
    validation.entities = observations;
    for (std::size_t index = 0; index < validation.entities.size(); ++index) {
        if (index == std::numeric_limits<std::uint64_t>::max())
            return fail(ErrorCode::resourceExhausted, "Observation count exceeds persistent ID space");
        validation.entities[index].id = EntityId{static_cast<std::uint64_t>(index) + 1U};
    }
    return validateSnapshot(validation);
}

} // namespace

Result<AssociationResult> associateObservations(const WorldSnapshot& previous, TimestampNs timestamp,
                                                 std::vector<EntityState> observations,
                                                 std::uint64_t nextEntityId,
                                                 AssociationPolicy policy) {
    if (!std::isfinite(policy.maximumCenterDistanceMeters) ||
        policy.maximumCenterDistanceMeters <= 0.0F || !std::isfinite(policy.minimumScore) ||
        policy.minimumScore < 0.0F) {
        return fail(ErrorCode::invalidArgument,
                    "Entity association policy requires finite positive distance and score bounds");
    }
    if (auto result = validateSnapshot(previous); !result)
        return std::unexpected(result.error());
    if (timestamp <= previous.timestamp) {
        return fail(ErrorCode::invalidArgument,
                    "Associated observation snapshot must be newer than the previous world state");
    }
    if (auto result = validateObservationPayload(timestamp, observations); !result)
        return std::unexpected(result.error());

    std::unordered_map<std::uint64_t, std::size_t> previousIndexById;
    previousIndexById.reserve(previous.entities.size());
    std::uint64_t maximumKnownId{};
    for (std::size_t index = 0; index < previous.entities.size(); ++index) {
        const std::uint64_t id = previous.entities[index].id.value;
        previousIndexById.emplace(id, index);
        maximumKnownId = std::max(maximumKnownId, id);
    }

    std::unordered_set<std::uint64_t> explicitIds;
    explicitIds.reserve(observations.size());
    std::vector<bool> previousMatched(previous.entities.size(), false);
    std::vector<bool> observationMatched(observations.size(), false);

    AssociationResult result;
    for (std::size_t index = 0; index < observations.size(); ++index) {
        EntityState& observation = observations[index];
        if (!observation.id.valid())
            continue;
        if (!explicitIds.insert(observation.id.value).second) {
            return fail(ErrorCode::invalidArgument, "Observation set contains duplicate explicit ID",
                        std::to_string(observation.id.value));
        }
        maximumKnownId = std::max(maximumKnownId, observation.id.value);
        observationMatched[index] = true;
        const auto previousMatch = previousIndexById.find(observation.id.value);
        if (previousMatch != previousIndexById.end()) {
            if (previousMatched[previousMatch->second]) {
                return fail(ErrorCode::invalidArgument,
                            "Multiple observations claim the same previous persistent entity",
                            std::to_string(observation.id.value));
            }
            previousMatched[previousMatch->second] = true;
            ++result.reusedIds;
        }
    }

    std::vector<Candidate> candidates;
    candidates.reserve(observations.size() * std::min<std::size_t>(previous.entities.size(), 32U));
    for (std::size_t observationIndex = 0; observationIndex < observations.size(); ++observationIndex) {
        if (observationMatched[observationIndex])
            continue;
        const EntityState& observation = observations[observationIndex];
        for (std::size_t previousIndex = 0; previousIndex < previous.entities.size(); ++previousIndex) {
            if (previousMatched[previousIndex])
                continue;
            const EntityState& prior = previous.entities[previousIndex];
            if (!semanticCompatible(prior, observation, policy))
                continue;
            const float distance = simd_distance(center(prior.worldBounds), center(observation.worldBounds));
            if (distance > policy.maximumCenterDistanceMeters)
                continue;
            const float score = associationScore(prior, observation, distance, policy);
            if (score < policy.minimumScore)
                continue;
            candidates.push_back(
                Candidate{observationIndex, previousIndex, score, distance, prior.id.value});
        }
    }

    std::sort(candidates.begin(), candidates.end(), [](const Candidate& lhs, const Candidate& rhs) {
        if (lhs.score != rhs.score)
            return lhs.score > rhs.score;
        if (lhs.centerDistance != rhs.centerDistance)
            return lhs.centerDistance < rhs.centerDistance;
        if (lhs.previousId != rhs.previousId)
            return lhs.previousId < rhs.previousId;
        return lhs.observationIndex < rhs.observationIndex;
    });

    for (const Candidate& candidate : candidates) {
        if (observationMatched[candidate.observationIndex] || previousMatched[candidate.previousIndex])
            continue;
        observations[candidate.observationIndex].id = previous.entities[candidate.previousIndex].id;
        observationMatched[candidate.observationIndex] = true;
        previousMatched[candidate.previousIndex] = true;
        ++result.reusedIds;
    }

    std::uint64_t allocation = std::max(nextEntityId, maximumKnownId);
    if (allocation != std::numeric_limits<std::uint64_t>::max())
        ++allocation;

    for (std::size_t index = 0; index < observations.size(); ++index) {
        EntityState& observation = observations[index];
        if (observationMatched[index]) {
            if (observation.lastObserved == 0)
                observation.lastObserved = timestamp;
            continue;
        }
        if (allocation == 0 || allocation == std::numeric_limits<std::uint64_t>::max()) {
            return fail(ErrorCode::resourceExhausted, "Persistent entity ID space is exhausted");
        }
        observation.id = EntityId{allocation};
        observation.lastObserved = observation.lastObserved == 0 ? timestamp : observation.lastObserved;
        observationMatched[index] = true;
        ++result.createdIds;
        ++allocation;
    }

    result.missingPreviousEntities = static_cast<std::size_t>(
        std::count(previousMatched.begin(), previousMatched.end(), false));
    result.nextEntityId = allocation;
    result.snapshot.timestamp = timestamp;
    result.snapshot.entities = std::move(observations);
    if (auto validation = validateSnapshot(result.snapshot); !validation)
        return std::unexpected(validation.error());
    return result;
}

} // namespace aether::world
