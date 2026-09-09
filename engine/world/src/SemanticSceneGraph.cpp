#include <aether/world/SemanticSceneGraph.hpp>

#include <algorithm>
#include <cmath>
#include <limits>
#include <optional>
#include <vector>

namespace aether::world {
namespace {

struct SweepItem final {
    std::size_t nodeIndex{};
    EntityId id{};
    Bounds bounds;
    float minimumX{};
    float maximumX{};
    float volume{};
};

struct ParentCandidate final {
    EntityId id{};
    float volume{std::numeric_limits<float>::infinity()};
};

[[nodiscard]] float boundsVolume(const Bounds& bounds) noexcept {
    const simd_float3 extent =
        simd_max(bounds.maximum - bounds.minimum, simd_float3{0.0F, 0.0F, 0.0F});
    return extent.x * extent.y * extent.z;
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

[[nodiscard]] bool strictContains(const SweepItem& outer, const SweepItem& inner) noexcept {
    if (!contains(outer.bounds, inner.bounds))
        return false;
    constexpr float epsilon = 1.0e-6F;
    return outer.volume > inner.volume + epsilon;
}

[[nodiscard]] float boundsSeparation(const Bounds& lhs, const Bounds& rhs) noexcept {
    const simd_float3 separation{
        std::max({lhs.minimum.x - rhs.maximum.x, rhs.minimum.x - lhs.maximum.x, 0.0F}),
        std::max({lhs.minimum.y - rhs.maximum.y, rhs.minimum.y - lhs.maximum.y, 0.0F}),
        std::max({lhs.minimum.z - rhs.maximum.z, rhs.minimum.z - lhs.maximum.z, 0.0F}),
    };
    return simd_length(separation);
}

void considerParent(std::vector<ParentCandidate>& parents, std::size_t childIndex,
                    const SweepItem& container) {
    ParentCandidate& current = parents[childIndex];
    if (!current.id.valid() || container.volume < current.volume ||
        (container.volume == current.volume && container.id < current.id)) {
        current.id = container.id;
        current.volume = container.volume;
    }
}

[[nodiscard]] bool edgeLess(const SceneGraphEdge& lhs, const SceneGraphEdge& rhs) noexcept {
    if (lhs.kind != rhs.kind)
        return lhs.kind < rhs.kind;
    if (lhs.source != rhs.source)
        return lhs.source < rhs.source;
    return lhs.target < rhs.target;
}

} // namespace

Result<SemanticSceneGraph> SemanticSceneGraph::build(const WorldSnapshot& snapshot,
                                                     SceneGraphPolicy policy) {
    if (auto validation = validateSnapshot(snapshot); !validation)
        return std::unexpected(validation.error());
    if (!std::isfinite(policy.nearDistanceMeters) || policy.nearDistanceMeters < 0.0F ||
        policy.maximumCandidatePairs == 0 || policy.maximumEdges == 0) {
        return fail(ErrorCode::invalidArgument,
                    "Semantic scene graph policy requires finite distance and non-zero budgets");
    }

    SemanticSceneGraph graph;
    graph.revision_ = snapshot.revision;
    graph.timestamp_ = snapshot.timestamp;
    graph.nodes_.reserve(snapshot.entities.size());
    graph.nodeIndexById_.reserve(snapshot.entities.size());

    std::vector<SweepItem> sweep;
    sweep.reserve(snapshot.entities.size());
    for (const EntityState& entity : snapshot.entities) {
        const std::size_t nodeIndex = graph.nodes_.size();
        graph.nodes_.push_back(SceneGraphNode{entity.id, entity.semanticLabel, {}, {}});
        graph.nodeIndexById_.emplace(entity.id.value, nodeIndex);
        graph.semanticIndex_[entity.semanticLabel].push_back(entity.id);
        sweep.push_back(SweepItem{nodeIndex, entity.id, entity.worldBounds,
                                 entity.worldBounds.minimum.x, entity.worldBounds.maximum.x,
                                 boundsVolume(entity.worldBounds)});
    }

    for (auto& [label, ids] : graph.semanticIndex_) {
        static_cast<void>(label);
        std::sort(ids.begin(), ids.end());
    }

    std::sort(sweep.begin(), sweep.end(), [](const SweepItem& lhs, const SweepItem& rhs) {
        if (lhs.minimumX != rhs.minimumX)
            return lhs.minimumX < rhs.minimumX;
        return lhs.id < rhs.id;
    });

    std::vector<std::size_t> active;
    active.reserve(sweep.size());
    std::vector<ParentCandidate> parents(graph.nodes_.size());
    std::vector<SceneGraphEdge> relationEdges;
    std::size_t candidatePairs{};

    for (std::size_t currentIndex = 0; currentIndex < sweep.size(); ++currentIndex) {
        const SweepItem& current = sweep[currentIndex];
        active.erase(std::remove_if(active.begin(), active.end(), [&](std::size_t index) {
                         return sweep[index].maximumX + policy.nearDistanceMeters < current.minimumX;
                     }),
                     active.end());

        for (const std::size_t activeIndex : active) {
            if (++candidatePairs > policy.maximumCandidatePairs) {
                return fail(ErrorCode::resourceExhausted,
                            "Semantic scene graph exceeds candidate-pair budget");
            }
            const SweepItem& other = sweep[activeIndex];
            const float separation = boundsSeparation(other.bounds, current.bounds);
            if (separation > policy.nearDistanceMeters)
                continue;

            const bool otherContainsCurrent = strictContains(other, current);
            const bool currentContainsOther = strictContains(current, other);
            if (otherContainsCurrent) {
                considerParent(parents, current.nodeIndex, other);
                continue;
            }
            if (currentContainsOther) {
                considerParent(parents, other.nodeIndex, current);
                continue;
            }

            if (relationEdges.size() >= policy.maximumEdges)
                return fail(ErrorCode::resourceExhausted, "Semantic scene graph exceeds edge budget");

            const EntityId source = other.id < current.id ? other.id : current.id;
            const EntityId target = other.id < current.id ? current.id : other.id;
            relationEdges.push_back(SceneGraphEdge{
                source,
                target,
                intersects(other.bounds, current.bounds) ? SceneRelationKind::intersects
                                                          : SceneRelationKind::near,
                separation,
            });
        }
        active.push_back(currentIndex);
    }

    for (std::size_t childIndex = 0; childIndex < parents.size(); ++childIndex) {
        const ParentCandidate parent = parents[childIndex];
        if (!parent.id.valid())
            continue;
        SceneGraphNode& child = graph.nodes_[childIndex];
        child.parent = parent.id;
        const auto parentIndex = graph.nodeIndexById_.find(parent.id.value);
        if (parentIndex == graph.nodeIndexById_.end())
            return fail(ErrorCode::internal, "Scene graph parent identity disappeared during build");
        graph.nodes_[parentIndex->second].children.push_back(child.id);
        if (relationEdges.size() >= policy.maximumEdges)
            return fail(ErrorCode::resourceExhausted, "Semantic scene graph exceeds edge budget");
        relationEdges.push_back(
            SceneGraphEdge{parent.id, child.id, SceneRelationKind::contains, 0.0F});
    }

    for (SceneGraphNode& node : graph.nodes_)
        std::sort(node.children.begin(), node.children.end());
    std::sort(graph.nodes_.begin(), graph.nodes_.end(), [](const SceneGraphNode& lhs,
                                                          const SceneGraphNode& rhs) {
        return lhs.id < rhs.id;
    });
    graph.nodeIndexById_.clear();
    graph.nodeIndexById_.reserve(graph.nodes_.size());
    for (std::size_t index = 0; index < graph.nodes_.size(); ++index)
        graph.nodeIndexById_.emplace(graph.nodes_[index].id.value, index);

    std::sort(relationEdges.begin(), relationEdges.end(), edgeLess);
    graph.edges_ = std::move(relationEdges);
    return graph;
}

const SceneGraphNode* SemanticSceneGraph::node(EntityId id) const noexcept {
    const auto match = nodeIndexById_.find(id.value);
    return match == nodeIndexById_.end() ? nullptr : &nodes_[match->second];
}

std::vector<EntityId> SemanticSceneGraph::semantic(std::string_view label) const {
    const auto match = semanticIndex_.find(std::string(label));
    return match == semanticIndex_.end() ? std::vector<EntityId>{} : match->second;
}

} // namespace aether::world
