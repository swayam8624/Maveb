#include <aether/world_gaussian/GaussianRegionIndex.hpp>

#include <algorithm>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <random>
#include <vector>

namespace {

using aether::gaussian::Gaussian;
using aether::gaussian::GaussianAsset;
using aether::world::EntityId;
using aether::world::RegionKey;
using aether::world::RegionUpdate;
using aether::world::SelectiveUpdatePlan;
using aether::world_gaussian::GaussianEntityOwnership;
using aether::world_gaussian::GaussianRegionIndex;

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

SelectiveUpdatePlan makePlan() {
    SelectiveUpdatePlan plan;
    plan.cellSizeMeters = 1.0F;

    RegionUpdate a;
    a.key = RegionKey{1, 2, 3};
    a.entities = {EntityId{1}};
    plan.dirtyRegions.push_back(a);

    RegionUpdate b;
    b.key = RegionKey{4, 2, 3};
    b.entities = {EntityId{2}};
    plan.dirtyRegions.push_back(b);
    return plan;
}

void testIndexedSelectionMatchesFullScanExactly() {
    GaussianAsset asset;
    GaussianEntityOwnership ownership;

    std::mt19937 generator(42);
    std::uniform_real_distribution<float> position(-20.0F, 20.0F);
    std::uniform_int_distribution<int> owner(0, 3);

    constexpr std::size_t count = 100'000;
    asset.gaussians.reserve(count + 4);
    ownership.owners.reserve(count + 4);

    for (std::size_t index = 0; index < count; ++index) {
        asset.gaussians.push_back(gaussian(position(generator), position(generator),
                                           position(generator)));
        ownership.owners.push_back(EntityId{static_cast<std::uint64_t>(owner(generator))});
    }

    asset.gaussians.push_back(gaussian(1.2F, 2.2F, 3.2F));
    ownership.owners.push_back(EntityId{1});
    asset.gaussians.push_back(gaussian(1.4F, 2.4F, 3.4F));
    ownership.owners.push_back(EntityId{3});
    asset.gaussians.push_back(gaussian(4.2F, 2.2F, 3.2F));
    ownership.owners.push_back(EntityId{2});
    asset.gaussians.push_back(gaussian(4.4F, 2.4F, 3.4F));
    ownership.owners.push_back(EntityId{});

    const auto plan = makePlan();
    const auto reference =
        aether::world_gaussian::selectGaussiansForLocalUpdate(asset, plan, &ownership);
    auto index = GaussianRegionIndex::create(asset, plan.cellSizeMeters);
    expect(reference.has_value() && index.has_value(),
           "reference selector and region index must initialize");
    if (!reference || !index)
        return;

    const auto indexed = index->select(plan, &ownership);
    expect(indexed.has_value(), "indexed selection must succeed");
    if (!indexed)
        return;

    expect(reference->gaussianIndices == indexed->selection.gaussianIndices,
           "indexed selector must return exactly the same Gaussian indices as full scan");
    expect(reference->ownedMatches == indexed->selection.ownedMatches,
           "indexed selector must preserve owned-match semantics");
    expect(reference->conservativeUnownedMatches ==
               indexed->selection.conservativeUnownedMatches,
           "indexed selector must preserve unowned conservative matches");
    expect(reference->rejectedStableOwnedGaussians ==
               indexed->selection.rejectedStableOwnedGaussians,
           "indexed selector must preserve stable-owner rejection semantics");
    expect(reference->unaffectedGaussians == indexed->selection.unaffectedGaussians,
           "indexed selector must preserve unaffected count");

    expect(indexed->statistics.candidateGaussiansVisited < asset.gaussians.size() / 20,
           "two dirty cells in a broad world should visit far below a full Gaussian scan");
}

void testIndexRejectsMismatchedCellSize() {
    GaussianAsset asset;
    asset.gaussians = {gaussian(0.1F, 0.2F, 0.3F)};
    auto index = GaussianRegionIndex::create(asset, 1.0F);
    expect(index.has_value(), "single-Gaussian region index must build");
    if (!index)
        return;

    SelectiveUpdatePlan plan;
    plan.cellSizeMeters = 0.5F;
    expect(!index->select(plan).has_value(),
           "index must fail closed when world-update grid does not match indexed grid");
}

} // namespace

int main() noexcept {
    try {
        testIndexedSelectionMatchesFullScanExactly();
        testIndexRejectsMismatchedCellSize();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Gaussian region index tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
