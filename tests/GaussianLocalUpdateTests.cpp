#include <aether/world_gaussian/GaussianLocalUpdate.hpp>

#include <cstdlib>
#include <exception>
#include <iostream>

namespace {

using aether::gaussian::Gaussian;
using aether::gaussian::GaussianAsset;
using aether::world::EntityId;
using aether::world::RegionKey;
using aether::world::RegionUpdate;
using aether::world::SelectiveUpdatePlan;
using aether::world_gaussian::GaussianEntityOwnership;
using aether::world_gaussian::GaussianLocalUpdatePolicy;

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
    const auto rejected =
        aether::world_gaussian::selectGaussiansForLocalUpdate(asset, oneDirtyCell(), nullptr, budget);
    expect(!rejected.has_value(), "local Gaussian selection must enforce affected-splat budget");
}

} // namespace

int main() noexcept {
    try {
        testOwnershipProtectsStableSplatsInDirtyCells();
        testOwnedTranslationIsTransactional();
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
