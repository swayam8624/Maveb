#include <aether/world_gaussian/GaussianEntityEdit.hpp>

#include <aether/world/WorldEdit.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <new>
#include <vector>

namespace aether::world_gaussian {
namespace {

[[nodiscard]] const world::EntityState* findEntity(const world::WorldSnapshot& snapshot,
                                                   world::EntityId entity) noexcept {
    const auto match =
        std::find_if(snapshot.entities.begin(), snapshot.entities.end(),
                     [entity](const world::EntityState& state) { return state.id == entity; });
    return match == snapshot.entities.end() ? nullptr : &*match;
}

[[nodiscard]] Result<std::vector<std::size_t>>
ownedIndices(const gaussian::GaussianAsset& asset, const GaussianEntityOwnership& ownership,
             world::EntityId entity, std::size_t maximum) {
    if (!entity.valid())
        return fail(ErrorCode::invalidArgument, "Gaussian entity edit ID cannot be zero");
    if (maximum == 0)
        return fail(ErrorCode::invalidArgument, "Gaussian entity edit budget cannot be zero");
    if (ownership.owners.size() != asset.gaussians.size())
        return fail(ErrorCode::invalidArgument,
                    "Gaussian ownership count must match Gaussian primitive count");

    std::vector<std::size_t> result;
    result.reserve(std::min(asset.gaussians.size(), maximum));
    for (std::size_t index = 0; index < ownership.owners.size(); ++index) {
        if (ownership.owners[index] != entity)
            continue;
        if (result.size() >= maximum)
            return fail(ErrorCode::resourceExhausted,
                        "Gaussian entity edit exceeds affected-primitive budget");
        result.push_back(index);
    }
    if (result.empty())
        return fail(ErrorCode::notFound, "Gaussian entity owns no primitives");
    return result;
}

[[nodiscard]] bool finite3(simd_float3 value) noexcept {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}

[[nodiscard]] simd_float3 rotateVector(simd_float3 value, simd_quatf rotation) noexcept {
    const simd_float4 q = rotation.vector;
    const simd_float3 u{q.x, q.y, q.z};
    return value + 2.0F * simd_cross(u, simd_cross(u, value) + q.w * value);
}

[[nodiscard]] std::array<float, 4>
composeGaussianRotation(simd_quatf delta, const std::array<float, 4>& current) noexcept {
    const simd_float4 q = delta.vector;
    const float dw = q.w;
    const float dx = q.x;
    const float dy = q.y;
    const float dz = q.z;
    const float cw = current[0];
    const float cx = current[1];
    const float cy = current[2];
    const float cz = current[3];
    std::array<float, 4> result{
        dw * cw - dx * cx - dy * cy - dz * cz,
        dw * cx + dx * cw + dy * cz - dz * cy,
        dw * cy - dx * cz + dy * cw + dz * cx,
        dw * cz + dx * cy - dy * cx + dz * cw,
    };
    double norm2{};
    for (const float value : result)
        norm2 += static_cast<double>(value) * value;
    if (!std::isfinite(norm2) || norm2 <= 1.0e-20)
        return {std::numeric_limits<float>::quiet_NaN(), 0.0F, 0.0F, 0.0F};
    const float inverse = static_cast<float>(1.0 / std::sqrt(norm2));
    for (float& value : result)
        value *= inverse;
    return result;
}

[[nodiscard]] world::Bounds rotatedBounds(const world::Bounds& bounds, simd_float3 pivot,
                                          simd_quatf rotation) noexcept {
    world::Bounds result;
    result.minimum = {
        std::numeric_limits<float>::infinity(),
        std::numeric_limits<float>::infinity(),
        std::numeric_limits<float>::infinity(),
    };
    result.maximum = {
        -std::numeric_limits<float>::infinity(),
        -std::numeric_limits<float>::infinity(),
        -std::numeric_limits<float>::infinity(),
    };
    for (int mask = 0; mask < 8; ++mask) {
        const simd_float3 corner{
            (mask & 1) ? bounds.maximum.x : bounds.minimum.x,
            (mask & 2) ? bounds.maximum.y : bounds.minimum.y,
            (mask & 4) ? bounds.maximum.z : bounds.minimum.z,
        };
        const simd_float3 transformed = pivot + rotateVector(corner - pivot, rotation);
        result.minimum = simd_min(result.minimum, transformed);
        result.maximum = simd_max(result.maximum, transformed);
    }
    return result;
}

[[nodiscard]] world::Bounds scaledBounds(const world::Bounds& bounds, simd_float3 pivot,
                                         float factor) noexcept {
    world::Bounds result;
    const simd_float3 a = pivot + factor * (bounds.minimum - pivot);
    const simd_float3 b = pivot + factor * (bounds.maximum - pivot);
    result.minimum = simd_min(a, b);
    result.maximum = simd_max(a, b);
    return result;
}

[[nodiscard]] Result<void> validateEdit(const GaussianEntityEdit& edit) {
    switch (edit.kind) {
    case GaussianEntityEditKind::rotation:
        if (!finite3(edit.rotationAxis) || !std::isfinite(edit.rotationRadians) ||
            std::abs(edit.rotationRadians) <= 1.0e-6F || simd_length(edit.rotationAxis) <= 1.0e-6F)
            return fail(ErrorCode::invalidArgument,
                        "Gaussian rotation edit requires finite non-zero axis/angle");
        break;
    case GaussianEntityEditKind::uniformScale:
        if (!std::isfinite(edit.uniformScale) || edit.uniformScale <= 0.0F ||
            std::abs(edit.uniformScale - 1.0F) <= 1.0e-6F)
            return fail(ErrorCode::invalidArgument,
                        "Gaussian uniform scale edit must be finite, positive, and non-identity");
        break;
    case GaussianEntityEditKind::opacity:
        if (!std::isfinite(edit.opacityLogitDelta) || std::abs(edit.opacityLogitDelta) <= 1.0e-6F)
            return fail(ErrorCode::invalidArgument,
                        "Gaussian opacity edit requires a finite non-zero logit delta");
        break;
    }
    return {};
}

} // namespace

Result<PersistentGaussianAttributeEditResult> editPersistentGaussianEntityIndexed(
    world::PersistentWorldModel& worldModel, gaussian::GaussianAsset& asset,
    const GaussianEntityOwnership& ownership, GaussianOverlaySpatialIndex& spatialIndex,
    world::EntityId entity, const GaussianEntityEdit& edit, world::TimestampNs timestamp,
    world::WorldEditPolicy worldPolicy, GaussianLocalUpdatePolicy gaussianPolicy) {
    if (auto valid = validateEdit(edit); !valid)
        return std::unexpected(valid.error());
    const world::WorldSnapshot* latest = worldModel.latest();
    if (!latest)
        return fail(ErrorCode::notFound,
                    "Persistent Gaussian attribute edit requires an existing world");
    if (timestamp <= latest->timestamp)
        return fail(ErrorCode::invalidArgument,
                    "Gaussian attribute edit timestamp must advance world history");
    const world::EntityState* state = findEntity(*latest, entity);
    if (!state)
        return fail(ErrorCode::notFound, "Persistent Gaussian entity was not found");
    if (spatialIndex.primitiveCount() != asset.gaussians.size())
        return fail(ErrorCode::invalidArgument,
                    "Gaussian overlay index primitive count does not match asset");
    if (spatialIndex.cellSizeMeters() != worldPolicy.selectiveUpdate.cellSizeMeters)
        return fail(ErrorCode::invalidArgument,
                    "Gaussian overlay index cell size does not match world edit policy");

    auto indices = ownedIndices(asset, ownership, entity, gaussianPolicy.maximumAffectedGaussians);
    if (!indices)
        return std::unexpected(indices.error());

    world::EntityPatch patch;
    patch.id = entity;
    simd_quatf deltaRotation = simd_quaternion(0.0F, simd_float3{0.0F, 1.0F, 0.0F});
    if (edit.kind == GaussianEntityEditKind::rotation) {
        const simd_float3 axis = simd_normalize(edit.rotationAxis);
        deltaRotation = simd_quaternion(edit.rotationRadians, axis);
        scene::Transform transform = state->transform;
        transform.rotation = simd_normalize(simd_mul(deltaRotation, transform.rotation));
        patch.transform = transform;
        patch.worldBounds = rotatedBounds(state->worldBounds, state->transform.translation,
                                          deltaRotation);
    } else if (edit.kind == GaussianEntityEditKind::uniformScale) {
        scene::Transform transform = state->transform;
        transform.scale *= edit.uniformScale;
        patch.transform = transform;
        patch.worldBounds =
            scaledBounds(state->worldBounds, state->transform.translation, edit.uniformScale);
    } else {
        patch.appearanceSignature =
            state->appearanceSignature ^ static_cast<std::uint64_t>(0x9e3779b97f4a7c15ULL);
    }

    auto prepared = world::prepareWorldEdit(*latest, timestamp, {patch}, worldPolicy);
    if (!prepared)
        return std::unexpected(prepared.error());

    GaussianOverlaySelectionDiagnostics diagnostics;
    auto selection = selectGaussiansForLocalUpdateIndexed(
        asset, prepared->selectiveUpdate, spatialIndex, &ownership, gaussianPolicy, &diagnostics);
    if (!selection)
        return std::unexpected(selection.error());

    std::vector<gaussian::Gaussian> replacements;
    std::vector<GaussianRelocation> relocations;
    try {
        replacements.reserve(indices->size());
        relocations.reserve(indices->size());
    } catch (const std::bad_alloc&) {
        return fail(ErrorCode::resourceExhausted,
                    "Gaussian entity edit could not allocate preflight storage");
    }

    const simd_float3 pivot = state->transform.translation;
    const float logFactor =
        edit.kind == GaussianEntityEditKind::uniformScale ? std::log(edit.uniformScale) : 0.0F;
    for (const std::size_t index : *indices) {
        if (index >= asset.gaussians.size())
            return fail(ErrorCode::corruptData, "Owned Gaussian index is out of range");
        const gaussian::Gaussian& current = asset.gaussians[index];
        gaussian::Gaussian replacement = current;
        const simd_float3 oldPosition{
            current.position[0], current.position[1], current.position[2],
        };

        if (edit.kind == GaussianEntityEditKind::rotation) {
            const simd_float3 next = pivot + rotateVector(oldPosition - pivot, deltaRotation);
            replacement.position = {next.x, next.y, next.z};
            replacement.rotation = composeGaussianRotation(deltaRotation, current.rotation);
        } else if (edit.kind == GaussianEntityEditKind::uniformScale) {
            const simd_float3 next = pivot + edit.uniformScale * (oldPosition - pivot);
            replacement.position = {next.x, next.y, next.z};
            for (std::size_t axis = 0; axis < 3; ++axis)
                replacement.logScale[axis] += logFactor;
        } else {
            replacement.opacityLogit += edit.opacityLogitDelta;
        }

        const simd_float3 newPosition{
            replacement.position[0], replacement.position[1], replacement.position[2],
        };
        if (!finite3(newPosition) || !std::isfinite(replacement.opacityLogit) ||
            std::ranges::any_of(replacement.logScale,
                                [](float value) { return !std::isfinite(value) || value < -30.0F ||
                                                         value > 30.0F; }) ||
            std::ranges::any_of(replacement.rotation,
                                [](float value) { return !std::isfinite(value); }))
            return fail(ErrorCode::resourceExhausted,
                        "Gaussian entity edit produced unsafe primitive state");

        replacements.push_back(replacement);
        if (edit.kind != GaussianEntityEditKind::opacity)
            relocations.push_back(GaussianRelocation{index, oldPosition, newPosition});
    }

    auto committed = worldModel.edit(timestamp, {patch}, worldPolicy);
    if (!committed)
        return std::unexpected(committed.error());

    for (std::size_t local = 0; local < indices->size(); ++local)
        asset.gaussians[(*indices)[local]] = replacements[local];

    bool overlayValid = true;
    bool overlayCompacted = false;
    if (!relocations.empty()) {
        if (auto updated = spatialIndex.applyRelocations(relocations); !updated) {
            auto compacted = spatialIndex.compact(asset);
            if (compacted)
                overlayCompacted = true;
            else
                overlayValid = false;
        }
    }

    return PersistentGaussianAttributeEditResult{
        .worldEdit = std::move(*committed),
        .editedGaussians = indices->size(),
        .reoptimizationSelection = std::move(*selection),
        .usedOverlayIndex = true,
        .overlayIndexValid = overlayValid,
        .overlayIndexCompacted = overlayCompacted,
        .overlayDiagnostics = diagnostics,
    };
}

} // namespace aether::world_gaussian
