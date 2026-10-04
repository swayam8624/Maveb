#include <aether/world_gaussian/GaussianLocalUpdate.hpp>
#include <aether/world_gaussian/GaussianOverlaySpatialIndex.hpp>

#include <cstdlib>
#include <exception>
#include <initializer_list>
#include <iostream>
#include <span>
#include <vector>

namespace {

using aether::gaussian::Gaussian;
using aether::gaussian::GaussianAsset;
using aether::world::EntityId;
using aether::world::RegionKey;
using aether::world::RegionUpdate;
using aether::world::SelectiveUpdatePlan;
using aether::world_gaussian::GaussianEntityOwnership;
using aether::world_gaussian::GaussianOverlaySelectionDiagnostics;
using aether::world_gaussian::GaussianOverlaySpatialIndex;
using aether::world_gaussian::GaussianOverlaySpatialIndexPolicy;
using aether::world_gaussian::GaussianRelocation;

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

SelectiveUpdatePlan dirtyCells(std::initializer_list<RegionKey> keys) {
    SelectiveUpdatePlan plan;
    plan.cellSizeMeters = 1.0F;
    for (const RegionKey key : keys) {
        RegionUpdate update;
        update.key = key;
        update.entities = {EntityId{1}};
        plan.dirtyRegions.push_back(update);
    }
    return plan;
}

void testOverlayMatchesFullScanAcrossRelocationAndReturnToBase() {
    GaussianAsset asset;
    asset.gaussians = {
        gaussian(0.1F, 0.1F, 0.1F), gaussian(0.2F, 0.1F, 0.1F), gaussian(1.1F, 0.1F, 0.1F),
        gaussian(2.1F, 0.1F, 0.1F), gaussian(5.1F, 0.1F, 0.1F),
    };
    GaussianEntityOwnership ownership;
    ownership.owners = {EntityId{1}, EntityId{2}, EntityId{1}, EntityId{}, EntityId{1}};

    auto index = GaussianOverlaySpatialIndex::build(asset, 1.0F);
    expect(index.has_value(), "overlay fixture must build");
    if (!index)
        return;

    const auto initialPlan = dirtyCells({RegionKey{0, 0, 0}});
    const auto scanInitial =
        aether::world_gaussian::selectGaussiansForLocalUpdate(asset, initialPlan, &ownership);
    GaussianOverlaySelectionDiagnostics initialDiagnostics;
    const auto overlayInitial = aether::world_gaussian::selectGaussiansForLocalUpdateIndexed(
        asset, initialPlan, *index, &ownership, {}, &initialDiagnostics);
    expect(scanInitial.has_value() && overlayInitial.has_value(),
           "scan and overlay must both select initial dirty cell");
    if (!scanInitial || !overlayInitial)
        return;
    expect(scanInitial->gaussianIndices == overlayInitial->gaussianIndices,
           "overlay must exactly match scan before relocation");
    expect(initialDiagnostics.deltaEntriesVisited == 0,
           "fresh overlay must not inspect delta entries");

    const simd_float3 oldPosition{5.1F, 0.1F, 0.1F};
    const simd_float3 newPosition{0.8F, 0.1F, 0.1F};
    const GaussianRelocation move{4, oldPosition, newPosition};
    expect(index->applyRelocations(std::span<const GaussianRelocation>(&move, 1)).has_value(),
           "overlay must accept exact cell-crossing relocation");
    asset.gaussians[4].position = {newPosition.x, newPosition.y, newPosition.z};

    const auto movedPlan = dirtyCells({RegionKey{0, 0, 0}, RegionKey{5, 0, 0}});
    const auto scanMoved =
        aether::world_gaussian::selectGaussiansForLocalUpdate(asset, movedPlan, &ownership);
    GaussianOverlaySelectionDiagnostics movedDiagnostics;
    const auto overlayMoved = aether::world_gaussian::selectGaussiansForLocalUpdateIndexed(
        asset, movedPlan, *index, &ownership, {}, &movedDiagnostics);
    expect(scanMoved.has_value() && overlayMoved.has_value(),
           "scan and overlay must both select moved world");
    if (!scanMoved || !overlayMoved)
        return;
    expect(scanMoved->gaussianIndices == overlayMoved->gaussianIndices,
           "overlay must exactly match scan after relocation");
    expect(movedDiagnostics.deltaEntriesVisited == 1,
           "new region must expose exactly one moved delta entry");
    expect(movedDiagnostics.staleBaseEntriesSkipped == 1,
           "old region query must explicitly skip one stale base entry");

    const auto movedStats = index->statistics();
    expect(movedStats.deltaEntries == 1 && movedStats.movedPrimitives == 1,
           "one relocated primitive must occupy one overlay delta entry");

    const GaussianRelocation returnToBase{4, newPosition, oldPosition};
    expect(
        index->applyRelocations(std::span<const GaussianRelocation>(&returnToBase, 1)).has_value(),
        "overlay must accept relocation back to immutable base cell");
    asset.gaussians[4].position = {oldPosition.x, oldPosition.y, oldPosition.z};

    const auto returnedStats = index->statistics();
    expect(returnedStats.deltaEntries == 0 && returnedStats.movedPrimitives == 0,
           "returning to original base cell must eliminate overlay delta state");

    const auto scanReturned =
        aether::world_gaussian::selectGaussiansForLocalUpdate(asset, movedPlan, &ownership);
    const auto overlayReturned = aether::world_gaussian::selectGaussiansForLocalUpdateIndexed(
        asset, movedPlan, *index, &ownership);
    expect(scanReturned.has_value() && overlayReturned.has_value() &&
               scanReturned->gaussianIndices == overlayReturned->gaussianIndices,
           "overlay must remain exactly equivalent after returning primitive to base");
}

void testRelocationBatchRejectsStaleAndDuplicateStateAtomically() {
    GaussianAsset asset;
    asset.gaussians = {
        gaussian(0.1F, 0.1F, 0.1F),
        gaussian(1.1F, 0.1F, 0.1F),
        gaussian(2.1F, 0.1F, 0.1F),
    };
    auto index = GaussianOverlaySpatialIndex::build(asset, 1.0F);
    expect(index.has_value(), "transactional overlay fixture must build");
    if (!index)
        return;

    const auto before = index->statistics();
    const std::vector<GaussianRelocation> duplicate{
        {0, simd_float3{0.1F, 0.1F, 0.1F}, simd_float3{3.1F, 0.1F, 0.1F}},
        {0, simd_float3{0.1F, 0.1F, 0.1F}, simd_float3{4.1F, 0.1F, 0.1F}},
    };
    expect(!index->applyRelocations(duplicate).has_value(),
           "duplicate primitive updates in one revision must fail closed");
    expect(index->statistics().deltaEntries == before.deltaEntries,
           "duplicate rejection must not mutate overlay delta state");

    const GaussianRelocation stale{1, simd_float3{9.1F, 0.1F, 0.1F}, simd_float3{4.1F, 0.1F, 0.1F}};
    expect(!index->applyRelocations(std::span<const GaussianRelocation>(&stale, 1)).has_value(),
           "stale old position must reject relocation");
    expect(index->statistics().deltaEntries == before.deltaEntries,
           "stale relocation rejection must be non-mutating");

    const std::vector<GaussianRelocation> valid{
        {0, simd_float3{0.1F, 0.1F, 0.1F}, simd_float3{3.1F, 0.1F, 0.1F}},
        {2, simd_float3{2.1F, 0.1F, 0.1F}, simd_float3{4.1F, 0.1F, 0.1F}},
    };
    expect(index->applyRelocations(valid).has_value(),
           "valid multi-primitive relocation transaction must commit");
    expect(index->statistics().deltaEntries == 2,
           "two committed relocations must produce two delta entries");
}

void testDeltaBudgetAndCompactionThresholdAreExplicit() {
    GaussianAsset asset;
    asset.gaussians = {
        gaussian(0.1F, 0.1F, 0.1F),
        gaussian(1.1F, 0.1F, 0.1F),
        gaussian(2.1F, 0.1F, 0.1F),
        gaussian(3.1F, 0.1F, 0.1F),
    };

    GaussianOverlaySpatialIndexPolicy policy;
    policy.maximumDeltaEntries = 2;
    policy.compactionFraction = 0.5;
    auto index = GaussianOverlaySpatialIndex::build(asset, 1.0F, policy);
    expect(index.has_value(), "bounded overlay fixture must build");
    if (!index)
        return;

    const std::vector<GaussianRelocation> tooLarge{
        {0, simd_float3{0.1F, 0.1F, 0.1F}, simd_float3{10.1F, 0.1F, 0.1F}},
        {1, simd_float3{1.1F, 0.1F, 0.1F}, simd_float3{11.1F, 0.1F, 0.1F}},
        {2, simd_float3{2.1F, 0.1F, 0.1F}, simd_float3{12.1F, 0.1F, 0.1F}},
    };
    expect(!index->applyRelocations(tooLarge).has_value(),
           "delta budget overflow must reject entire relocation revision");
    expect(index->statistics().deltaEntries == 0,
           "delta overflow must not partially publish overlay state");

    const std::vector<GaussianRelocation> atBudget{
        {0, simd_float3{0.1F, 0.1F, 0.1F}, simd_float3{10.1F, 0.1F, 0.1F}},
        {1, simd_float3{1.1F, 0.1F, 0.1F}, simd_float3{11.1F, 0.1F, 0.1F}},
    };
    expect(index->applyRelocations(atBudget).has_value(),
           "relocation batch at configured delta budget must commit");
    expect(index->statistics().compactionRecommended,
           "50 percent cumulative delta must cross explicit compaction threshold");

    asset.gaussians[0].position = {10.1F, 0.1F, 0.1F};
    asset.gaussians[1].position = {11.1F, 0.1F, 0.1F};
    expect(index->compact(asset).has_value(),
           "explicit compaction must rebuild from authoritative current asset");
    const auto compacted = index->statistics();
    expect(compacted.deltaEntries == 0 && !compacted.compactionRecommended,
           "compaction must clear delta state and reset threshold");
}

} // namespace

int main() noexcept {
    try {
        testOverlayMatchesFullScanAcrossRelocationAndReturnToBase();
        testRelocationBatchRejectsStaleAndDuplicateStateAtomically();
        testDeltaBudgetAndCompactionThresholdAreExplicit();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Gaussian overlay spatial index tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
