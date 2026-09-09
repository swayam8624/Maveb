#pragma once

#include <aether/world/SelectiveUpdate.hpp>

#include <optional>
#include <string>
#include <vector>

namespace aether::world {

/// Sparse authored mutation of one already-persistent entity.
struct EntityPatch final {
    EntityId id{};
    bool remove{};
    std::optional<std::string> name;
    std::optional<std::string> semanticLabel;
    std::optional<scene::Transform> transform;
    std::optional<Bounds> worldBounds;
    std::optional<RepresentationKind> representation;
    std::optional<std::uint64_t> geometrySignature;
    std::optional<std::uint64_t> appearanceSignature;
    std::optional<float> confidence;
};

struct WorldEditPolicy final {
    DiffPolicy diff;
    SelectiveUpdatePolicy selectiveUpdate;
};

struct WorldEditResult final {
    WorldSnapshot candidate;
    WorldDiff diff;
    SelectiveUpdatePlan selectiveUpdate;
    std::size_t updatedEntities{};
    std::size_t removedEntities{};
};

/// Applies sparse edits to a candidate snapshot without mutating committed timeline state.
///
/// Translation-only transform patches automatically translate the entity bounds. Rotation/scale
/// changes require explicit replacement world bounds because the temporal layer intentionally does
/// not own source geometry needed to recompute a rotated/scaled AABB.
[[nodiscard]] Result<WorldEditResult> prepareWorldEdit(const WorldSnapshot& previous,
                                                       TimestampNs timestamp,
                                                       const std::vector<EntityPatch>& patches,
                                                       WorldEditPolicy policy = {});

} // namespace aether::world
