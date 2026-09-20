#include <aether/gaussian/GaussianAsset.hpp>
#include <aether/world/PersistentWorld.hpp>
#include <aether/world/SelectiveUpdate.hpp>
#include <aether/world_gaussian/GaussianLocalUpdate.hpp>

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <string_view>
#include <vector>

namespace {

using aether::gaussian::Gaussian;
using aether::gaussian::GaussianAsset;
using aether::world::Bounds;
using aether::world::EntityId;
using aether::world::EntityState;
using aether::world::RepresentationKind;
using aether::world::SelectiveUpdatePolicy;
using aether::world::WorldSnapshot;
using aether::world_gaussian::GaussianEntityOwnership;

constexpr std::size_t kGridWidth = 10;
constexpr std::size_t kEntityCount = kGridWidth * kGridWidth;
constexpr std::size_t kGaussiansPerEntity = 4;

EntityState entity(std::size_t index, float translationX) {
    const std::size_t row = index / kGridWidth;
    const std::size_t column = index % kGridWidth;
    const float baseX = static_cast<float>(column) * 1.5F;
    const float baseZ = static_cast<float>(row) * 1.5F;

    EntityState result;
    result.id = EntityId{static_cast<std::uint64_t>(index) + 1U};
    result.name = "synthetic-region";
    result.semanticLabel = "fixture";
    result.transform.translation = {baseX + translationX, 0.0F, baseZ};
    result.worldBounds =
        Bounds{{baseX - 0.25F + translationX, -0.25F, baseZ - 0.25F},
               {baseX + 0.25F + translationX, 0.25F, baseZ + 0.25F}};
    result.representation = RepresentationKind::gaussian;
    result.geometrySignature = static_cast<std::uint64_t>(index) + 1000U;
    result.appearanceSignature = static_cast<std::uint64_t>(index) + 2000U;
    result.confidence = 1.0F;
    result.lastObserved = 100;
    return result;
}

std::vector<std::size_t> changedIndices(std::size_t count, bool scattered) {
    std::vector<std::size_t> result;
    result.reserve(count);
    if (!scattered) {
        for (std::size_t index = 0; index < count; ++index)
            result.push_back(index);
        return result;
    }

    const double stride = static_cast<double>(kEntityCount) / static_cast<double>(count);
    for (std::size_t sample = 0; sample < count; ++sample) {
        const auto candidate = static_cast<std::size_t>(static_cast<double>(sample) * stride);
        result.push_back(std::min(candidate, kEntityCount - 1U));
    }
    std::sort(result.begin(), result.end());
    result.erase(std::unique(result.begin(), result.end()), result.end());
    for (std::size_t candidate = 0; result.size() < count && candidate < kEntityCount; ++candidate) {
        if (!std::binary_search(result.begin(), result.end(), candidate))
            result.push_back(candidate);
    }
    std::sort(result.begin(), result.end());
    return result;
}

void buildFixture(WorldSnapshot& before, WorldSnapshot& after, GaussianAsset& asset,
                  GaussianEntityOwnership& ownership, std::size_t changedCount, bool scattered) {
    before.revision = 1;
    before.timestamp = 100;
    after.revision = 2;
    after.timestamp = 200;
    before.entities.reserve(kEntityCount);
    after.entities.reserve(kEntityCount);
    asset.gaussians.reserve(kEntityCount * kGaussiansPerEntity);
    ownership.owners.reserve(kEntityCount * kGaussiansPerEntity);

    const std::vector<std::size_t> changed = changedIndices(changedCount, scattered);
    for (std::size_t index = 0; index < kEntityCount; ++index) {
        const bool isChanged = std::binary_search(changed.begin(), changed.end(), index);
        before.entities.push_back(entity(index, 0.0F));
        after.entities.push_back(entity(index, isChanged ? 0.12F : 0.0F));
        after.entities.back().lastObserved = 200;

        const EntityState& state = before.entities.back();
        constexpr std::array<float, kGaussiansPerEntity> offsets{-0.12F, -0.04F, 0.04F, 0.12F};
        for (const float offset : offsets) {
            Gaussian gaussian;
            gaussian.position = {state.transform.translation.x + offset, 0.0F,
                                 state.transform.translation.z};
            asset.gaussians.push_back(gaussian);
            ownership.owners.push_back(state.id);
        }
    }
}

void emitCase(std::size_t changedCount, bool scattered, float cellSize, std::uint32_t halo) {
    WorldSnapshot before;
    WorldSnapshot after;
    GaussianAsset asset;
    GaussianEntityOwnership ownership;
    buildFixture(before, after, asset, ownership, changedCount, scattered);

    auto diff = aether::world::diffSnapshots(before, after);
    if (!diff) {
        std::cerr << diff.error().describe() << '\n';
        std::exit(3);
    }

    SelectiveUpdatePolicy policy;
    policy.cellSizeMeters = cellSize;
    policy.haloCells = halo;
    auto update = aether::world::planSelectiveUpdates(before, after, *diff, policy);
    if (!update) {
        std::cerr << update.error().describe() << '\n';
        std::exit(4);
    }

    auto selection =
        aether::world_gaussian::selectGaussiansForLocalUpdate(asset, *update, &ownership);
    if (!selection) {
        std::cerr << selection.error().describe() << '\n';
        std::exit(5);
    }

    const double changedFraction =
        static_cast<double>(changedCount) / static_cast<double>(kEntityCount);
    const double gaussianLocality =
        static_cast<double>(selection->gaussianIndices.size()) /
        static_cast<double>(asset.gaussians.size());

    std::cout << "{\"changedEntities\":" << changedCount << ",\"changedFraction\":"
              << changedFraction << ",\"pattern\":\"" << (scattered ? "scattered" : "clustered")
              << "\",\"cellSizeMeters\":" << cellSize << ",\"haloCells\":" << halo
              << ",\"dirtyRegions\":" << update->dirtyRegions.size()
              << ",\"selectedGaussians\":" << selection->gaussianIndices.size()
              << ",\"totalGaussians\":" << asset.gaussians.size()
              << ",\"gaussianUpdateLocalityRatio\":" << gaussianLocality
              << ",\"rejectedStableOwnedGaussians\":"
              << selection->rejectedStableOwnedGaussians
              << ",\"unaffectedGaussians\":" << selection->unaffectedGaussians << '}';
}

int run() {
    constexpr std::array<std::size_t, 7> changedCounts{1, 2, 5, 10, 25, 50, 100};
    constexpr std::array<float, 3> cellSizes{0.25F, 0.50F, 1.00F};
    constexpr std::array<std::uint32_t, 3> halos{0, 1, 2};

    std::cout << "{\"schemaVersion\":1,\"probe\":\"update-locality-baseline\","
                 "\"entityCount\":"
              << kEntityCount << ",\"gaussiansPerEntity\":" << kGaussiansPerEntity
              << ",\"cases\":[";
    bool first = true;
    for (const bool scattered : {false, true}) {
        for (const std::size_t changedCount : changedCounts) {
            for (const float cellSize : cellSizes) {
                for (const std::uint32_t halo : halos) {
                    if (!first)
                        std::cout << ',';
                    first = false;
                    emitCase(changedCount, scattered, cellSize, halo);
                }
            }
        }
    }
    std::cout << "]}\n";
    return 0;
}

} // namespace

int main() noexcept {
    try {
        return run();
    } catch (const std::exception& error) {
        std::cerr << "Unhandled update-locality probe failure: " << error.what() << '\n';
    } catch (...) {
        std::cerr << "Unhandled update-locality probe failure\n";
    }
    return EXIT_FAILURE;
}
