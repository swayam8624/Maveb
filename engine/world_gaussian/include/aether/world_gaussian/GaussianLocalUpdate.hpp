#pragma once

#include <aether/gaussian/GaussianAsset.hpp>
#include <aether/world_gaussian/GaussianSpatialIndex.hpp>
#include <aether/world_gaussian/GaussianOverlaySpatialIndex.hpp>
#include <aether/world/LocalityLedger.hpp>
#include <aether/world/SelectiveUpdate.hpp>
#include <aether/world/WorldModel.hpp>

#include <cstddef>
#include <vector>

namespace aether::world_gaussian {

/// Optional persistent-entity ownership for each Gaussian primitive.
/// `owners[i] == 0` means the splat has not yet been confidently assigned to one entity.
struct GaussianEntityOwnership final {
    std::vector<world::EntityId> owners;
};

struct GaussianLocalUpdatePolicy final {
    std::size_t maximumAffectedGaussians{5'000'000};
    bool includeUnownedGaussians{true};
};

struct GaussianLocalUpdateSelection final {
    std::vector<std::size_t> gaussianIndices;
    std::size_t ownedMatches{};
    std::size_t conservativeUnownedMatches{};
    std::size_t rejectedStableOwnedGaussians{};
    std::size_t unaffectedGaussians{};
    /// Number of primitives whose ownership/selection state was actually inspected.
    std::size_t inspectedGaussians{};
};

/// Records the selector's primitive-inspection work against the exact full-scene scan baseline.
/// This does not record gaussiansUpdated because selection is only eligibility for later work.
[[nodiscard]] Result<void> recordGaussianSelectionLocality(
    const gaussian::GaussianAsset& asset, const GaussianLocalUpdateSelection& selection,
    world::LocalityLedger& ledger);

struct PersistentGaussianTranslationResult final {
    world::WorldEditResult worldEdit;
    std::size_t translatedGaussians{};
    GaussianLocalUpdateSelection reoptimizationSelection;
};

/// Maps halo-expanded persistent-world dirty regions to the exact Gaussian primitives that may be
/// reconsidered by local deformation/re-optimization.
///
/// When ownership is supplied, splats owned by stable entities are intentionally rejected even if
/// they occupy the same dirty metric cell; unowned boundary splats may be included conservatively.
[[nodiscard]] Result<GaussianLocalUpdateSelection> selectGaussiansForLocalUpdate(
    const gaussian::GaussianAsset& asset, const world::SelectiveUpdatePlan& worldUpdate,
    const GaussianEntityOwnership* ownership = nullptr, GaussianLocalUpdatePolicy policy = {});

/// Indexed equivalent of selectGaussiansForLocalUpdate().
/// It must preserve the exact selected primitive set and ownership accounting while inspecting only
/// primitives that occupy dirty RegionKey buckets.
[[nodiscard]] Result<GaussianLocalUpdateSelection> selectGaussiansForLocalUpdateIndexed(
    const gaussian::GaussianAsset& asset, const world::SelectiveUpdatePlan& worldUpdate,
    const GaussianSpatialIndex& spatialIndex,
    const GaussianEntityOwnership* ownership = nullptr, GaussianLocalUpdatePolicy policy = {});

struct GaussianOverlaySelectionDiagnostics final {
    std::size_t dirtyRegionsQueried{};
    std::size_t baseEntriesVisited{};
    std::size_t staleBaseEntriesSkipped{};
    std::size_t deltaEntriesVisited{};
};

/// Compact base+delta indexed equivalent used to test revision-local spatial maintenance.
/// The selected primitive set and ownership semantics must remain identical to the scan oracle.
[[nodiscard]] Result<GaussianLocalUpdateSelection> selectGaussiansForLocalUpdateIndexed(
    const gaussian::GaussianAsset& asset, const world::SelectiveUpdatePlan& worldUpdate,
    const GaussianOverlaySpatialIndex& spatialIndex,
    const GaussianEntityOwnership* ownership = nullptr, GaussianLocalUpdatePolicy policy = {},
    GaussianOverlaySelectionDiagnostics* diagnostics = nullptr);

/// Applies a rigid translation to every Gaussian owned by one stable persistent entity.
/// Gaussian scale, rotation, opacity, and SH appearance remain unchanged under pure translation.
[[nodiscard]] Result<std::size_t>
translateOwnedGaussians(gaussian::GaussianAsset& asset, const GaussianEntityOwnership& ownership,
                        world::EntityId entity, simd_float3 translationDelta,
                        std::size_t maximumAffectedGaussians = 5'000'000);

/// Commits one authored persistent-entity translation and its owned Gaussian field as a single
/// logical transaction. Gaussian work is fully preflighted before the append-only World revision is
/// committed; once the World commit succeeds, applying the already-validated Gaussian translation
/// is non-failing. The returned local selection identifies splats eligible for subsequent bounded
/// appearance re-optimization while protecting stable owned neighbors.
[[nodiscard]] Result<PersistentGaussianTranslationResult> translatePersistentGaussianEntity(
    world::PersistentWorldModel& worldModel, gaussian::GaussianAsset& asset,
    const GaussianEntityOwnership& ownership, world::EntityId entity,
    simd_float3 targetWorldTranslation, world::TimestampNs timestamp,
    world::WorldEditPolicy worldPolicy = {}, GaussianLocalUpdatePolicy gaussianPolicy = {});

} // namespace aether::world_gaussian
