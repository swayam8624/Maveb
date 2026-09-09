#pragma once

#include <aether/world/PersistentWorld.hpp>

#include <cstddef>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace aether::world {

struct SpatialQueryPolicy final {
    std::size_t maximumResults{4096};
    float maximumDistanceMeters{1000.0F};
};

struct SpatialHit final {
    EntityId id{};
    float pointToBoundsMeters{};
    float centerDistanceMeters{};
};

struct SpatialRelations final {
    EntityId subject{};
    EntityId reference{};
    float centerDistanceMeters{};
    float boundsSeparationMeters{};
    bool intersects{};
    bool subjectContainsReference{};
    bool subjectInsideReference{};
    bool near{};
};

/// Immutable semantic/spatial index derived from one committed persistent-world revision.
///
/// The index intentionally does not infer labels. It exposes deterministic engine primitives that
/// future scene understanding and language layers can safely compose: exact semantic lookup,
/// nearest-object queries, region queries, and metric object-to-object relations.
class SemanticSpatialIndex final {
  public:
    [[nodiscard]] static Result<SemanticSpatialIndex> build(const WorldSnapshot& snapshot);

    [[nodiscard]] std::uint64_t revision() const noexcept {
        return revision_;
    }

    [[nodiscard]] TimestampNs timestamp() const noexcept {
        return timestamp_;
    }

    [[nodiscard]] std::size_t size() const noexcept {
        return entities_.size();
    }

    /// Returns stable IDs whose semantic label exactly matches `semanticLabel`.
    [[nodiscard]] Result<std::vector<EntityId>>
    findSemantic(std::string_view semanticLabel, std::size_t maximumResults = 4096) const;

    /// Returns entities ordered by point-to-AABB distance and then stable ID.
    /// Empty semanticLabel means all entities; otherwise the semantic label must match exactly.
    [[nodiscard]] Result<std::vector<SpatialHit>>
    nearest(simd_float3 worldPoint, std::string_view semanticLabel = {},
            SpatialQueryPolicy policy = {}) const;

    /// Returns entities whose metric AABB intersects the supplied region.
    /// Empty semanticLabel means all entities.
    [[nodiscard]] Result<std::vector<EntityId>>
    intersecting(const Bounds& region, std::string_view semanticLabel = {},
                 std::size_t maximumResults = 4096) const;

    /// Computes symmetric proximity/intersection and directional containment relations.
    [[nodiscard]] Result<SpatialRelations> relations(EntityId subject, EntityId reference,
                                                      float nearDistanceMeters = 1.0F) const;

  private:
    struct IndexedEntity final {
        EntityId id{};
        std::string semanticLabel;
        Bounds bounds;
    };

    [[nodiscard]] const IndexedEntity* entity(EntityId id) const noexcept;
    [[nodiscard]] const std::vector<std::size_t>* semanticCandidates(std::string_view label) const;

    std::uint64_t revision_{};
    TimestampNs timestamp_{};
    std::vector<IndexedEntity> entities_;
    std::unordered_map<std::string, std::vector<std::size_t>> bySemantic_;
    std::unordered_map<std::uint64_t, std::size_t> indexById_;
};

} // namespace aether::world
