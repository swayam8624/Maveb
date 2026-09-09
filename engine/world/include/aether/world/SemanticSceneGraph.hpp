#pragma once

#include <aether/world/PersistentWorld.hpp>

#include <cstddef>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace aether::world {

enum class SceneRelationKind : std::uint8_t {
    contains,
    intersects,
    near,
};

struct SceneGraphPolicy final {
    float nearDistanceMeters{1.0F};
    std::size_t maximumCandidatePairs{2'000'000};
    std::size_t maximumEdges{2'000'000};
};

struct SceneGraphNode final {
    EntityId id{};
    std::string semanticLabel;
    EntityId parent{};
    std::vector<EntityId> children;
};

struct SceneGraphEdge final {
    EntityId source{};
    EntityId target{};
    SceneRelationKind kind{SceneRelationKind::near};
    float boundsSeparationMeters{};
};

/// Deterministic semantic/spatial graph derived from one immutable persistent-world revision.
///
/// Containment uses only the smallest strict containing AABB as the immediate parent, preventing
/// transitive container clutter. Non-containing pairs receive one strongest relation: intersection
/// when their AABBs overlap, otherwise near when surface separation is within policy distance.
/// Candidate generation uses an X-axis sweep-and-prune window rather than blindly comparing every
/// entity pair, while explicit budgets bound adversarial dense scenes.
class SemanticSceneGraph final {
  public:
    [[nodiscard]] static Result<SemanticSceneGraph>
    build(const WorldSnapshot& snapshot, SceneGraphPolicy policy = {});

    [[nodiscard]] std::uint64_t revision() const noexcept {
        return revision_;
    }

    [[nodiscard]] TimestampNs timestamp() const noexcept {
        return timestamp_;
    }

    [[nodiscard]] const std::vector<SceneGraphNode>& nodes() const noexcept {
        return nodes_;
    }

    [[nodiscard]] const std::vector<SceneGraphEdge>& edges() const noexcept {
        return edges_;
    }

    [[nodiscard]] const SceneGraphNode* node(EntityId id) const noexcept;

    /// Returns stable node IDs with an exact semantic-label match, ordered by stable ID.
    [[nodiscard]] std::vector<EntityId> semantic(std::string_view label) const;

  private:
    std::uint64_t revision_{};
    TimestampNs timestamp_{};
    std::vector<SceneGraphNode> nodes_;
    std::vector<SceneGraphEdge> edges_;
    std::unordered_map<std::uint64_t, std::size_t> nodeIndexById_;
    std::unordered_map<std::string, std::vector<EntityId>> semanticIndex_;
};

} // namespace aether::world
