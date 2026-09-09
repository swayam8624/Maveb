#include <aether/world/SpatialSemantics.hpp>

#include <algorithm>
#include <cmath>
#include <limits>

namespace aether::world {
namespace {

[[nodiscard]] bool finitePoint(simd_float3 point) noexcept {
    return std::isfinite(point.x) && std::isfinite(point.y) && std::isfinite(point.z);
}

[[nodiscard]] bool validBounds(const Bounds& bounds) noexcept {
    return finitePoint(bounds.minimum) && finitePoint(bounds.maximum) &&
           bounds.minimum.x <= bounds.maximum.x && bounds.minimum.y <= bounds.maximum.y &&
           bounds.minimum.z <= bounds.maximum.z;
}

[[nodiscard]] simd_float3 center(const Bounds& bounds) noexcept {
    return (bounds.minimum + bounds.maximum) * 0.5F;
}

[[nodiscard]] float pointToBounds(simd_float3 point, const Bounds& bounds) noexcept {
    const simd_float3 closest = simd_min(simd_max(point, bounds.minimum), bounds.maximum);
    return simd_distance(point, closest);
}

[[nodiscard]] bool intersects(const Bounds& lhs, const Bounds& rhs) noexcept {
    return lhs.minimum.x <= rhs.maximum.x && lhs.maximum.x >= rhs.minimum.x &&
           lhs.minimum.y <= rhs.maximum.y && lhs.maximum.y >= rhs.minimum.y &&
           lhs.minimum.z <= rhs.maximum.z && lhs.maximum.z >= rhs.minimum.z;
}

[[nodiscard]] bool contains(const Bounds& outer, const Bounds& inner) noexcept {
    return outer.minimum.x <= inner.minimum.x && outer.minimum.y <= inner.minimum.y &&
           outer.minimum.z <= inner.minimum.z && outer.maximum.x >= inner.maximum.x &&
           outer.maximum.y >= inner.maximum.y && outer.maximum.z >= inner.maximum.z;
}

[[nodiscard]] float boundsSeparation(const Bounds& lhs, const Bounds& rhs) noexcept {
    const simd_float3 separation{
        std::max({lhs.minimum.x - rhs.maximum.x, rhs.minimum.x - lhs.maximum.x, 0.0F}),
        std::max({lhs.minimum.y - rhs.maximum.y, rhs.minimum.y - lhs.maximum.y, 0.0F}),
        std::max({lhs.minimum.z - rhs.maximum.z, rhs.minimum.z - lhs.maximum.z, 0.0F}),
    };
    return simd_length(separation);
}

} // namespace

Result<SemanticSpatialIndex> SemanticSpatialIndex::build(const WorldSnapshot& snapshot) {
    if (auto validation = validateSnapshot(snapshot); !validation)
        return std::unexpected(validation.error());

    SemanticSpatialIndex index;
    index.revision_ = snapshot.revision;
    index.timestamp_ = snapshot.timestamp;
    index.entities_.reserve(snapshot.entities.size());
    index.indexById_.reserve(snapshot.entities.size());

    for (const EntityState& state : snapshot.entities) {
        const std::size_t entityIndex = index.entities_.size();
        index.entities_.push_back(IndexedEntity{state.id, state.semanticLabel, state.worldBounds});
        index.indexById_.emplace(state.id.value, entityIndex);
        index.bySemantic_[state.semanticLabel].push_back(entityIndex);
    }

    for (auto& [label, candidates] : index.bySemantic_) {
        static_cast<void>(label);
        std::sort(candidates.begin(), candidates.end(), [&index](std::size_t lhs, std::size_t rhs) {
            return index.entities_[lhs].id < index.entities_[rhs].id;
        });
    }
    return index;
}

const SemanticSpatialIndex::IndexedEntity* SemanticSpatialIndex::entity(EntityId id) const noexcept {
    const auto match = indexById_.find(id.value);
    return match == indexById_.end() ? nullptr : &entities_[match->second];
}

const std::vector<std::size_t>*
SemanticSpatialIndex::semanticCandidates(std::string_view label) const {
    const auto match = bySemantic_.find(std::string(label));
    return match == bySemantic_.end() ? nullptr : &match->second;
}

Result<std::vector<EntityId>> SemanticSpatialIndex::findSemantic(std::string_view semanticLabel,
                                                                 std::size_t maximumResults) const {
    if (semanticLabel.empty())
        return fail(ErrorCode::invalidArgument, "Semantic lookup label cannot be empty");
    if (maximumResults == 0)
        return fail(ErrorCode::invalidArgument, "Semantic lookup result budget cannot be zero");

    std::vector<EntityId> result;
    const auto* candidates = semanticCandidates(semanticLabel);
    if (!candidates)
        return result;

    result.reserve(std::min(maximumResults, candidates->size()));
    for (const std::size_t index : *candidates) {
        if (result.size() == maximumResults)
            break;
        result.push_back(entities_[index].id);
    }
    return result;
}

Result<std::vector<SpatialHit>> SemanticSpatialIndex::nearest(simd_float3 worldPoint,
                                                              std::string_view semanticLabel,
                                                              SpatialQueryPolicy policy) const {
    if (!finitePoint(worldPoint))
        return fail(ErrorCode::invalidArgument, "Spatial query point must be finite");
    if (policy.maximumResults == 0 || !std::isfinite(policy.maximumDistanceMeters) ||
        policy.maximumDistanceMeters < 0.0F) {
        return fail(ErrorCode::invalidArgument,
                    "Spatial query requires a non-zero result budget and finite distance bound");
    }

    std::vector<SpatialHit> hits;
    const auto append = [&](const IndexedEntity& candidate) {
        const float boundsDistance = pointToBounds(worldPoint, candidate.bounds);
        if (boundsDistance > policy.maximumDistanceMeters)
            return;
        hits.push_back(SpatialHit{candidate.id, boundsDistance,
                                  simd_distance(worldPoint, center(candidate.bounds))});
    };

    if (semanticLabel.empty()) {
        hits.reserve(entities_.size());
        for (const IndexedEntity& candidate : entities_)
            append(candidate);
    } else if (const auto* candidates = semanticCandidates(semanticLabel)) {
        hits.reserve(candidates->size());
        for (const std::size_t index : *candidates)
            append(entities_[index]);
    }

    std::sort(hits.begin(), hits.end(), [](const SpatialHit& lhs, const SpatialHit& rhs) {
        if (lhs.pointToBoundsMeters != rhs.pointToBoundsMeters)
            return lhs.pointToBoundsMeters < rhs.pointToBoundsMeters;
        if (lhs.centerDistanceMeters != rhs.centerDistanceMeters)
            return lhs.centerDistanceMeters < rhs.centerDistanceMeters;
        return lhs.id < rhs.id;
    });
    if (hits.size() > policy.maximumResults)
        hits.resize(policy.maximumResults);
    return hits;
}

Result<std::vector<EntityId>> SemanticSpatialIndex::intersecting(const Bounds& region,
                                                                 std::string_view semanticLabel,
                                                                 std::size_t maximumResults) const {
    if (!validBounds(region))
        return fail(ErrorCode::invalidArgument, "Spatial intersection region is invalid");
    if (maximumResults == 0)
        return fail(ErrorCode::invalidArgument, "Spatial intersection result budget cannot be zero");

    std::vector<EntityId> result;
    const auto append = [&](const IndexedEntity& candidate) {
        if (intersects(region, candidate.bounds))
            result.push_back(candidate.id);
    };

    if (semanticLabel.empty()) {
        result.reserve(entities_.size());
        for (const IndexedEntity& candidate : entities_)
            append(candidate);
    } else if (const auto* candidates = semanticCandidates(semanticLabel)) {
        result.reserve(candidates->size());
        for (const std::size_t index : *candidates)
            append(entities_[index]);
    }

    std::sort(result.begin(), result.end());
    if (result.size() > maximumResults)
        result.resize(maximumResults);
    return result;
}

Result<SpatialRelations> SemanticSpatialIndex::relations(EntityId subject, EntityId reference,
                                                         float nearDistanceMeters) const {
    if (!subject.valid() || !reference.valid())
        return fail(ErrorCode::invalidArgument, "Spatial relation entity IDs cannot be zero");
    if (subject == reference)
        return fail(ErrorCode::invalidArgument,
                    "Spatial relation requires two different persistent entities");
    if (!std::isfinite(nearDistanceMeters) || nearDistanceMeters < 0.0F)
        return fail(ErrorCode::invalidArgument, "Spatial near-distance threshold is invalid");

    const IndexedEntity* subjectEntity = entity(subject);
    const IndexedEntity* referenceEntity = entity(reference);
    if (!subjectEntity)
        return fail(ErrorCode::notFound, "Spatial relation subject entity was not found",
                    std::to_string(subject.value));
    if (!referenceEntity)
        return fail(ErrorCode::notFound, "Spatial relation reference entity was not found",
                    std::to_string(reference.value));

    const float separation = boundsSeparation(subjectEntity->bounds, referenceEntity->bounds);
    return SpatialRelations{
        .subject = subject,
        .reference = reference,
        .centerDistanceMeters =
            simd_distance(center(subjectEntity->bounds), center(referenceEntity->bounds)),
        .boundsSeparationMeters = separation,
        .intersects = intersects(subjectEntity->bounds, referenceEntity->bounds),
        .subjectContainsReference = contains(subjectEntity->bounds, referenceEntity->bounds),
        .subjectInsideReference = contains(referenceEntity->bounds, subjectEntity->bounds),
        .near = separation <= nearDistanceMeters,
    };
}

} // namespace aether::world
