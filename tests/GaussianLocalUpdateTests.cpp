#include <aether/world_gaussian/GaussianLocalUpdate.hpp>
#include <aether/world_gaussian/GaussianSpatialIndex.hpp>

#include <cstdlib>
#include <exception>
#include <iostream>
#include <string>
#include <utility>

namespace {

using aether::gaussian::Gaussian;
using aether::gaussian::GaussianAsset;
using aether::world::Bounds;
using aether::world::EntityId;
using aether::world::EntityState;
using aether::world::PersistentWorldModel;
using aether::world::RegionKey;
using aether::world::RegionUpdate;
using aether::world::RepresentationKind;
using aether::world::SelectiveUpdatePlan;
using aether::world_gaussian::GaussianEntityOwnership;
using aether::world_gaussian::GaussianLocalUpdatePolicy;
using aether::world_gaussian::GaussianSpatialIndex;

int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

Gaussian gaussian(float x, float y, float z) {
    Gaussian result;
    result.position = {x, y, z};
    return result;
}

EntityState observation(std::string name, std::string semantic, float x) {
    EntityState result;
    result.name = std::move(name);
    result.semanticLabel = std::move(semantic);
    result.transform.translation = {x, 0.0F, 0.0F};
    result.worldBounds = Bounds{{x - 0.25F, -0.25F, -0.25F},
                                {x + 0.25F, 0.25F, 0.25F}};
    result.representation = RepresentationKind::gaussian;
    result.geometrySignature = 10;
    result.appearanceSignature = 20;
    return result;
}

SelectiveUpdatePlan oneDirtyCell() {
    SelectiveUpdatePlan plan;
    plan.cellSizeMeters = 1.0F;
    RegionUpdate region;
    region.key = RegionKey{0, 0, 0};
    region.entities = {EntityId{1}};
    plan.dirtyRegions.push_back(std::move(region));
    return plan;
}

void testOwnershipProtectsStableSplatsInDirtyCells() {
    GaussianAsset asset;
    asset.gaussians = {
        gaussian(0.2F, 0.2F, 0.2F),
        gaussian(0.4F, 0.2F, 0.2F),
        gaussian(0.6F, 0.2F, 0.2F),
        gaussian(2.0F, 0.0F, 0.0F),
    };
    GaussianEntityOwnership ownership;
    ownership.owners = {EntityId{1}, EntityId{2}, EntityId{}, EntityId{1}};

    const auto selected = aether::world_gaussian::selectGaussiansForLocalUpdate(
        asset, oneDirtyCell(), &ownership);
    expect(selected.has_value(), "owned Gaussian selection must accept valid world update plan");
    if (!selected)
        return;

    expect(selected->gaussianIndices.size() == 2 && selected->gaussianIndices[0] == 0 &&
               selected->gaussianIndices[1] == 2,
           "dirty region must select changed-owner and conservative unowned splats only");
    expect(selected->ownedMatches == 1, "changed persistent owner must contribute one exact match");
    expect(selected->conservativeUnownedMatches == 1,
           "unowned boundary Gaussian must be included conservatively by default");
    expect(selected->rejectedStableOwnedGaussians == 1,
           "stable entity splat in same dirty cell must be explicitly protected");
    expect(selected->unaffectedGaussians == 2,
           "stable rejected splat and spatially clean splat must remain unaffected");

    GaussianLocalUpdatePolicy strict;
    strict.includeUnownedGaussians = false;
    const auto strictSelected = aether::world_gaussian::selectGaussiansForLocalUpdate(
        asset, oneDirtyCell(), &ownership, strict);
    expect(strictSelected.has_value() && strictSelected->gaussianIndices.size() == 1 &&
               strictSelected->gaussianIndices.front() == 0,
           "strict ownership mode must exclude ambiguous unowned boundary splats");

    const auto spatialOnly =
        aether::world_gaussian::selectGaussiansForLocalUpdate(asset, oneDirtyCell());
    expect(spatialOnly.has_value() && spatialOnly->gaussianIndices.size() == 3,
           "without ownership, every Gaussian in a dirty metric cell must be selected spatially");
}


void testIndexedSelectionMatchesFullScanAndTracksInspections() {
    GaussianAsset asset;
    asset.gaussians = {
        gaussian(0.2F, 0.2F, 0.2F),
        gaussian(0.4F, 0.2F, 0.2F),
        gaussian(0.6F, 0.2F, 0.2F),
        gaussian(2.0F, 0.0F, 0.0F),
        gaussian(5.0F, 5.0F, 5.0F),
    };
    GaussianEntityOwnership ownership;
    ownership.owners = {EntityId{1}, EntityId{2}, EntityId{}, EntityId{1}, EntityId{2}};

    auto index = GaussianSpatialIndex::build(asset, oneDirtyCell().cellSizeMeters);
    expect(index.has_value(), "Gaussian spatial index must build for valid finite positions");
    if (!index)
        return;

    const auto scanned = aether::world_gaussian::selectGaussiansForLocalUpdate(
        asset, oneDirtyCell(), &ownership);
    const auto indexed = aether::world_gaussian::selectGaussiansForLocalUpdateIndexed(
        asset, oneDirtyCell(), *index, &ownership);
    expect(scanned.has_value() && indexed.has_value(),
           "scan and indexed local selections must both succeed");
    if (!scanned || !indexed)
        return;

    expect(scanned->gaussianIndices == indexed->gaussianIndices,
           "indexed selection must return exactly the same primitive indices as full scan");
    expect(scanned->ownedMatches == indexed->ownedMatches &&
               scanned->conservativeUnownedMatches == indexed->conservativeUnownedMatches &&
               scanned->rejectedStableOwnedGaussians == indexed->rejectedStableOwnedGaussians &&
               scanned->unaffectedGaussians == indexed->unaffectedGaussians,
           "indexed selection must preserve ownership accounting semantics");
    expect(scanned->inspectedGaussians == asset.gaussians.size(),
           "full scan instrumentation must count every primitive inspection");
    expect(indexed->inspectedGaussians == 3,
           "indexed selection must inspect only dirty-region primitives");

    const auto stats = index->statistics();
    expect(stats.primitiveCount == asset.gaussians.size() &&
               stats.storedIndexEntries == asset.gaussians.size(),
           "Gaussian spatial index must contain exactly one entry per primitive");

    const simd_float3 oldPosition{asset.gaussians[4].position[0],
                                  asset.gaussians[4].position[1],
                                  asset.gaussians[4].position[2]};
    const simd_float3 newPosition{0.8F, 0.2F, 0.2F};
    expect(index->relocateGaussian(4, oldPosition, newPosition).has_value(),
           "Gaussian spatial index must update cell-crossing membership");
    asset.gaussians[4].position = {newPosition.x, newPosition.y, newPosition.z};

    const auto rescanned = aether::world_gaussian::selectGaussiansForLocalUpdate(
        asset, oneDirtyCell(), &ownership);
    const auto reindexed = aether::world_gaussian::selectGaussiansForLocalUpdateIndexed(
        asset, oneDirtyCell(), *index, &ownership);
    expect(rescanned.has_value() && reindexed.has_value() &&
               rescanned->gaussianIndices == reindexed->gaussianIndices,
           "relocated index must remain selection-equivalent to full scan");
}


void testIndexedSelectionScalesWithDirtyPopulation() {
    GaussianAsset asset;
    GaussianEntityOwnership ownership;
    constexpr std::size_t regionCount = 100;
    constexpr std::size_t gaussiansPerRegion = 100;
    asset.gaussians.reserve(regionCount * gaussiansPerRegion);
    ownership.owners.reserve(regionCount * gaussiansPerRegion);

    for (std::size_t region = 0; region < regionCount; ++region) {
        const float baseX = static_cast<float>(region) + 0.1F;
        for (std::size_t local = 0; local < gaussiansPerRegion; ++local) {
            const float y = 0.001F * static_cast<float>(local);
            asset.gaussians.push_back(gaussian(baseX, y, 0.1F));
            ownership.owners.push_back(region == 37 ? EntityId{1} : EntityId{2});
        }
    }

    SelectiveUpdatePlan plan;
    plan.cellSizeMeters = 1.0F;
    RegionUpdate region;
    region.key = RegionKey{37, 0, 0};
    region.entities = {EntityId{1}};
    plan.dirtyRegions.push_back(region);

    auto index = GaussianSpatialIndex::build(asset, plan.cellSizeMeters);
    expect(index.has_value(), "large deterministic Gaussian spatial index must build");
    if (!index)
        return;

    const auto scanned =
        aether::world_gaussian::selectGaussiansForLocalUpdate(asset, plan, &ownership);
    const auto indexed = aether::world_gaussian::selectGaussiansForLocalUpdateIndexed(
        asset, plan, *index, &ownership);
    expect(scanned.has_value() && indexed.has_value(),
           "large full-scan and indexed selections must both succeed");
    if (!scanned || !indexed)
        return;

    expect(scanned->gaussianIndices == indexed->gaussianIndices,
           "large indexed selection must be exactly equivalent to full scan");
    expect(scanned->ownedMatches == indexed->ownedMatches &&
               scanned->conservativeUnownedMatches == indexed->conservativeUnownedMatches &&
               scanned->rejectedStableOwnedGaussians == indexed->rejectedStableOwnedGaussians &&
               scanned->unaffectedGaussians == indexed->unaffectedGaussians,
           "large indexed selection must preserve ownership accounting");
    expect(scanned->inspectedGaussians == asset.gaussians.size(),
           "large full scan must inspect every Gaussian");
    expect(indexed->inspectedGaussians == gaussiansPerRegion,
           "large indexed selection must inspect only the dirty-region Gaussian population");
    expect(indexed->gaussianIndices.size() == gaussiansPerRegion,
           "large indexed selection must return the exact dirty entity population");
}


void testIndexedSelectionScalesWithDirtyOccupancy() {
    constexpr std::size_t gaussianCount = 20'000;
    GaussianAsset asset;
    asset.gaussians.reserve(gaussianCount);

    // Spread primitives across one-dimensional metric cells. Exactly ten primitives occupy each
    // cell, with every coordinate strictly inside its bucket rather than on a cell boundary.
    for (std::size_t index = 0; index < gaussianCount; ++index) {
        const std::size_t cell = index / 10;
        const std::size_t local = index % 10;
        const float x = static_cast<float>(cell) + 0.05F +
                        0.08F * static_cast<float>(local);
        asset.gaussians.push_back(gaussian(x, 0.1F, 0.1F));
    }

    SelectiveUpdatePlan plan;
    plan.cellSizeMeters = 1.0F;
    RegionUpdate dirty;
    dirty.key = RegionKey{0, 0, 0};
    plan.dirtyRegions.push_back(dirty);

    auto spatialIndex = GaussianSpatialIndex::build(asset, plan.cellSizeMeters);
    expect(spatialIndex.has_value(),
           "large Gaussian spatial index fixture must build deterministically");
    if (!spatialIndex)
        return;

    const auto scanned =
        aether::world_gaussian::selectGaussiansForLocalUpdate(asset, plan);
    const auto indexed =
        aether::world_gaussian::selectGaussiansForLocalUpdateIndexed(asset, plan, *spatialIndex);
    expect(scanned.has_value() && indexed.has_value(),
           "large scan/index local-selection comparison must succeed");
    if (!scanned || !indexed)
        return;

    expect(scanned->gaussianIndices == indexed->gaussianIndices &&
               indexed->gaussianIndices.size() == 10,
           "indexed selection must exactly match full scan for sparse dirty occupancy");
    expect(scanned->inspectedGaussians == gaussianCount,
           "full scan must report inspection of every Gaussian primitive");
    expect(indexed->inspectedGaussians == 10,
           "indexed selection must inspect only Gaussian primitives in the dirty cell");
    expect(indexed->inspectedGaussians * 1'000 < scanned->inspectedGaussians,
           "indexed selection must demonstrate at least three orders of magnitude inspection "
           "reduction in sparse fixture");
}

void testSelectionLocalityLedgerUsesFullScanBaseline() {
    GaussianAsset asset;
    asset.gaussians = {
        gaussian(0.1F, 0.1F, 0.1F),
        gaussian(0.2F, 0.1F, 0.1F),
        gaussian(4.1F, 0.1F, 0.1F),
        gaussian(8.1F, 0.1F, 0.1F),
    };

    auto spatialIndex = GaussianSpatialIndex::build(asset, oneDirtyCell().cellSizeMeters);
    expect(spatialIndex.has_value(), "locality-ledger fixture spatial index must build");
    if (!spatialIndex)
        return;

    const auto indexed = aether::world_gaussian::selectGaussiansForLocalUpdateIndexed(
        asset, oneDirtyCell(), *spatialIndex);
    expect(indexed.has_value(), "locality-ledger fixture selection must succeed");
    if (!indexed)
        return;

    aether::world::LocalityLedger ledger;
    expect(aether::world_gaussian::recordGaussianSelectionLocality(asset, *indexed, ledger)
               .has_value(),
           "Gaussian selector must record unit-safe locality evidence");
    const auto counter = ledger.counter(aether::world::LocalityDomain::gaussiansInspected);
    expect(counter.incremental == indexed->inspectedGaussians &&
               counter.full == asset.gaussians.size(),
           "Gaussian locality ledger must use actual inspections over full-scene scan count");
}

void testOwnedTranslationIsTransactional() {
    GaussianAsset asset;
    asset.gaussians = {
        gaussian(0.0F, 0.0F, 0.0F),
        gaussian(1.0F, 0.0F, 0.0F),
        gaussian(2.0F, 0.0F, 0.0F),
    };
    GaussianEntityOwnership ownership;
    ownership.owners = {EntityId{7}, EntityId{7}, EntityId{8}};

    const auto rejected = aether::world_gaussian::translateOwnedGaussians(
        asset, ownership, EntityId{7}, simd_float3{1.0F, 2.0F, 3.0F}, 1);
    expect(!rejected.has_value(), "owned translation must reject work beyond configured budget");
    expect(asset.gaussians[0].position[0] == 0.0F && asset.gaussians[1].position[0] == 1.0F,
           "failed Gaussian translation must leave every primitive untouched");

    const auto moved = aether::world_gaussian::translateOwnedGaussians(
        asset, ownership, EntityId{7}, simd_float3{1.0F, 2.0F, 3.0F});
    expect(moved.has_value() && *moved == 2,
           "valid owned translation must report exact number of moved Gaussian primitives");
    expect(asset.gaussians[0].position[0] == 1.0F && asset.gaussians[0].position[1] == 2.0F &&
               asset.gaussians[0].position[2] == 3.0F,
           "first owned Gaussian must receive full translation delta");
    expect(asset.gaussians[1].position[0] == 2.0F,
           "second owned Gaussian must receive translation delta");
    expect(asset.gaussians[2].position[0] == 2.0F,
           "Gaussian owned by another stable entity must not move");
}

void testPersistentWorldAndGaussianTranslationCommitTogether() {
    PersistentWorldModel model;
    const auto initial = model.ingest(
        100, {observation("Chair", "chair", 0.0F), observation("Wall", "wall", 1.25F)});
    expect(initial.has_value(), "cross-representation transaction fixture must initialize world");
    if (!initial)
        return;

    GaussianAsset asset;
    asset.gaussians = {
        gaussian(0.0F, 0.0F, 0.0F),
        gaussian(0.1F, 0.0F, 0.0F),
        gaussian(1.2F, 0.0F, 0.0F),
    };
    GaussianEntityOwnership ownership;
    ownership.owners = {EntityId{1}, EntityId{1}, EntityId{2}};

    GaussianLocalUpdatePolicy impossible;
    impossible.maximumAffectedGaussians = 1;
    const auto rejected = aether::world_gaussian::translatePersistentGaussianEntity(
        model, asset, ownership, EntityId{1}, simd_float3{1.0F, 0.0F, 0.0F}, 200, {}, impossible);
    expect(!rejected.has_value(),
           "Gaussian preflight budget failure must reject cross-representation transaction");
    expect(model.timeline().size() == 1,
           "failed Gaussian preflight must not append persistent World revision");
    expect(asset.gaussians[0].position[0] == 0.0F && asset.gaussians[1].position[0] == 0.1F,
           "failed cross-representation transaction must not move any Gaussian");

    const auto committed = aether::world_gaussian::translatePersistentGaussianEntity(
        model, asset, ownership, EntityId{1}, simd_float3{1.0F, 0.0F, 0.0F}, 300);
    expect(committed.has_value(), "valid persistent Gaussian translation must commit atomically");
    if (!committed)
        return;

    expect(committed->worldEdit.candidate.revision == 2,
           "successful persistent Gaussian edit must create one new World revision");
    expect(committed->translatedGaussians == 2,
           "successful persistent Gaussian edit must translate all owned chair splats");
    expect(model.timeline().size() == 2,
           "successful cross-representation edit must append exactly one World revision");
    expect(model.latest() && model.latest()->entities.front().transform.translation.x == 1.0F,
           "persistent World entity transform must advance to authored target");
    expect(asset.gaussians[0].position[0] == 1.0F && asset.gaussians[1].position[0] == 1.1F,
           "owned Gaussian positions must advance with persistent entity transform");
    expect(asset.gaussians[2].position[0] == 1.2F,
           "stable neighboring entity Gaussian must remain untouched");
    expect(committed->reoptimizationSelection.rejectedStableOwnedGaussians >= 1,
           "local re-optimization selection must protect stable owned neighbors in dirty area");
}

void testOwnershipShapeAndSelectionBudgetFailClosed() {
    GaussianAsset asset;
    asset.gaussians = {gaussian(0.1F, 0.1F, 0.1F), gaussian(0.2F, 0.1F, 0.1F)};
    GaussianEntityOwnership invalidOwnership;
    invalidOwnership.owners = {EntityId{1}};
    const auto invalid = aether::world_gaussian::selectGaussiansForLocalUpdate(
        asset, oneDirtyCell(), &invalidOwnership);
    expect(!invalid.has_value(), "ownership vector must match Gaussian primitive cardinality");

    GaussianLocalUpdatePolicy budget;
    budget.maximumAffectedGaussians = 1;
    const auto rejected = aether::world_gaussian::selectGaussiansForLocalUpdate(
        asset, oneDirtyCell(), nullptr, budget);
    expect(!rejected.has_value(), "local Gaussian selection must enforce affected-splat budget");
}

} // namespace

int main() noexcept {
    try {
        testOwnershipProtectsStableSplatsInDirtyCells();
        testIndexedSelectionMatchesFullScanAndTracksInspections();
        testIndexedSelectionScalesWithDirtyOccupancy();
        testSelectionLocalityLedgerUsesFullScanBaseline();
        testIndexedSelectionScalesWithDirtyPopulation();
        testOwnedTranslationIsTransactional();
        testPersistentWorldAndGaussianTranslationCommitTogether();
        testOwnershipShapeAndSelectionBudgetFailClosed();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Gaussian local update tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
