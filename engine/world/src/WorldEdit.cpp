#include <aether/world/WorldEdit.hpp>

#include <algorithm>
#include <limits>
#include <unordered_set>

namespace aether::world {
namespace {

[[nodiscard]] bool sameRotationAndScale(const scene::Transform& lhs,
                                        const scene::Transform& rhs) noexcept {
    return simd_all(lhs.rotation.vector == rhs.rotation.vector) && simd_all(lhs.scale == rhs.scale);
}

[[nodiscard]] bool hasNonRemovalFields(const EntityPatch& patch) noexcept {
    return patch.name.has_value() || patch.semanticLabel.has_value() || patch.transform.has_value() ||
           patch.worldBounds.has_value() || patch.representation.has_value() ||
           patch.geometrySignature.has_value() || patch.appearanceSignature.has_value() ||
           patch.confidence.has_value();
}

} // namespace

Result<WorldEditResult> prepareWorldEdit(const WorldSnapshot& previous, TimestampNs timestamp,
                                         const std::vector<EntityPatch>& patches,
                                         WorldEditPolicy policy) {
    if (patches.empty())
        return fail(ErrorCode::invalidArgument, "Persistent world edit contains no entity patches");
    if (timestamp == 0 || timestamp <= previous.timestamp) {
        return fail(ErrorCode::invalidArgument,
                    "Persistent world edit timestamp must be newer than committed state");
    }
    if (previous.revision == std::numeric_limits<std::uint64_t>::max())
        return fail(ErrorCode::resourceExhausted, "Persistent world revision space is exhausted");
    if (auto validation = validateSnapshot(previous); !validation)
        return std::unexpected(validation.error());

    WorldEditResult result;
    result.candidate = previous;
    result.candidate.revision = previous.revision + 1U;
    result.candidate.timestamp = timestamp;

    std::unordered_set<std::uint64_t> patchedIds;
    patchedIds.reserve(patches.size());
    for (const EntityPatch& patch : patches) {
        if (!patch.id.valid())
            return fail(ErrorCode::invalidArgument, "Persistent world edit entity ID cannot be zero");
        if (!patchedIds.insert(patch.id.value).second) {
            return fail(ErrorCode::invalidArgument, "Persistent world edit contains duplicate entity ID",
                        std::to_string(patch.id.value));
        }
        if (patch.remove && hasNonRemovalFields(patch)) {
            return fail(ErrorCode::invalidArgument,
                        "Removal patch cannot contain replacement entity fields",
                        std::to_string(patch.id.value));
        }

        const auto match = std::find_if(result.candidate.entities.begin(), result.candidate.entities.end(),
                                        [&patch](const EntityState& entity) {
                                            return entity.id == patch.id;
                                        });
        if (match == result.candidate.entities.end()) {
            return fail(ErrorCode::notFound, "Persistent world edit entity was not found",
                        std::to_string(patch.id.value));
        }
        if (patch.remove) {
            result.candidate.entities.erase(match);
            ++result.removedEntities;
            continue;
        }

        EntityState& entity = *match;
        if (patch.transform) {
            if (!patch.worldBounds && !sameRotationAndScale(entity.transform, *patch.transform)) {
                return fail(ErrorCode::invalidArgument,
                            "Rotation or scale edits require explicit replacement world bounds",
                            std::to_string(patch.id.value));
            }
            if (!patch.worldBounds) {
                const simd_float3 translationDelta =
                    patch.transform->translation - entity.transform.translation;
                entity.worldBounds.minimum += translationDelta;
                entity.worldBounds.maximum += translationDelta;
            }
            entity.transform = *patch.transform;
        }
        if (patch.worldBounds)
            entity.worldBounds = *patch.worldBounds;
        if (patch.name)
            entity.name = *patch.name;
        if (patch.semanticLabel)
            entity.semanticLabel = *patch.semanticLabel;
        if (patch.representation)
            entity.representation = *patch.representation;
        if (patch.geometrySignature)
            entity.geometrySignature = *patch.geometrySignature;
        if (patch.appearanceSignature)
            entity.appearanceSignature = *patch.appearanceSignature;
        if (patch.confidence)
            entity.confidence = *patch.confidence;
        ++result.updatedEntities;
    }

    if (auto validation = validateSnapshot(result.candidate); !validation)
        return std::unexpected(validation.error());
    auto diff = diffSnapshots(previous, result.candidate, policy.diff);
    if (!diff)
        return std::unexpected(diff.error());
    const std::size_t changed = diff->summary.added + diff->summary.removed + diff->summary.modified;
    if (changed == 0)
        return fail(ErrorCode::invalidArgument, "Persistent world edit contains no effective changes");

    auto selectiveUpdate =
        planSelectiveUpdates(previous, result.candidate, *diff, policy.selectiveUpdate);
    if (!selectiveUpdate)
        return std::unexpected(selectiveUpdate.error());
    result.diff = std::move(*diff);
    result.selectiveUpdate = std::move(*selectiveUpdate);
    return result;
}

} // namespace aether::world
