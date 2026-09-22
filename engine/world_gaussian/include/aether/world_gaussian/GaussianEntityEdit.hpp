#pragma once

#include <aether/world_gaussian/GaussianLocalUpdate.hpp>

#include <cstddef>
#include <cstdint>

namespace aether::world_gaussian {

enum class GaussianEntityEditKind : std::uint8_t {
    rotation,
    uniformScale,
    opacity,
};

struct GaussianEntityEdit final {
    GaussianEntityEditKind kind{GaussianEntityEditKind::rotation};
    simd_float3 rotationAxis{0.0F, 1.0F, 0.0F};
    float rotationRadians{};
    float uniformScale{1.0F};
    float opacityLogitDelta{};
};

struct PersistentGaussianAttributeEditResult final {
    world::WorldEditResult worldEdit;
    std::size_t editedGaussians{};
    GaussianLocalUpdateSelection reoptimizationSelection;
    bool usedOverlayIndex{true};
    bool overlayIndexValid{true};
    bool overlayIndexCompacted{};
    GaussianOverlaySelectionDiagnostics overlayDiagnostics;
};

/// Applies one same-cardinality authored edit to all Gaussians owned by a persistent entity.
///
/// Supported edits deliberately preserve ownership/cardinality:
/// - rotation: rotate owned centers/covariances about the persistent entity origin;
/// - uniformScale: scale owned centers/covariances about the persistent entity origin;
/// - opacity: shift owned opacity logits and version the entity appearance signature.
///
/// Rotation replaces the entity AABB with the conservative AABB of the previous AABB's rotated
/// corners. Uniform scaling transforms the previous AABB about the entity origin. The world edit,
/// Gaussian mutation, and overlay-index relocation are preflighted before the authoritative world
/// revision is committed. Birth/death remains outside this API because it requires explicit
/// ownership/cardinality semantics.
[[nodiscard]] Result<PersistentGaussianAttributeEditResult>
editPersistentGaussianEntityIndexed(
    world::PersistentWorldModel& worldModel, gaussian::GaussianAsset& asset,
    const GaussianEntityOwnership& ownership, GaussianOverlaySpatialIndex& spatialIndex,
    world::EntityId entity, const GaussianEntityEdit& edit, world::TimestampNs timestamp,
    world::WorldEditPolicy worldPolicy = {}, GaussianLocalUpdatePolicy gaussianPolicy = {});

} // namespace aether::world_gaussian
