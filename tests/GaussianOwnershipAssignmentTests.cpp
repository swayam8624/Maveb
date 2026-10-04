#include <aether/world_gaussian/GaussianOwnershipAssignment.hpp>

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
using aether::world::RepresentationKind;
using aether::world::WorldSnapshot;
using aether::world_gaussian::GaussianOwnershipAssignmentPolicy;

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

EntityState entity(std::uint64_t id, std::string name, std::string semantic,
                   RepresentationKind representation, Bounds bounds) {
    EntityState result;
    result.id = EntityId{id};
    result.name = std::move(name);
    result.semanticLabel = std::move(semantic);
    result.representation = representation;
    result.worldBounds = bounds;
    result.lastObserved = 100;
    return result;
}

WorldSnapshot ownershipWorld() {
    WorldSnapshot snapshot;
    snapshot.revision = 3;
    snapshot.timestamp = 100;
    snapshot.entities = {
        entity(1, "Room", "room", RepresentationKind::hybrid,
               Bounds{{-10.0F, -10.0F, -10.0F}, {10.0F, 10.0F, 10.0F}}),
        entity(2, "Cup", "cup", RepresentationKind::gaussian,
               Bounds{{-0.5F, -0.5F, -0.5F}, {0.5F, 0.5F, 0.5F}}),
        entity(3, "Mesh Cabinet", "cabinet", RepresentationKind::mesh,
               Bounds{{4.0F, 0.0F, 0.0F}, {5.0F, 1.0F, 1.0F}}),
        entity(4, "Gaussian Chair", "chair", RepresentationKind::gaussian,
               Bounds{{2.0F, 0.0F, 0.0F}, {3.0F, 1.0F, 1.0F}}),
    };
    return snapshot;
}

void testSpecificContainersAndRepresentationFiltering() {
    GaussianAsset asset;
    asset.gaussians = {
        gaussian(0.0F, 0.0F, 0.0F),
        gaussian(2.5F, 0.5F, 0.5F),
        gaussian(4.5F, 0.5F, 0.5F),
        gaussian(12.0F, 0.0F, 0.0F),
    };
    const WorldSnapshot snapshot = ownershipWorld();

    const auto assigned = aether::world_gaussian::assignGaussianOwnership(asset, snapshot);
    expect(assigned.has_value(), "valid Gaussian world must assign persistent ownership");
    if (!assigned)
        return;

    expect(assigned->ownership.owners.size() == asset.gaussians.size(),
           "ownership assignment must preserve Gaussian cardinality exactly");
    expect(assigned->ownership.owners[0].value == 2,
           "Gaussian inside room and cup must choose smaller, more specific cup container");
    expect(assigned->ownership.owners[1].value == 4,
           "Gaussian inside Gaussian chair must receive chair stable identity");
    expect(assigned->ownership.owners[2].value == 1,
           "mesh-only cabinet must not steal Gaussian ownership when representation filter is on");
    expect(!assigned->ownership.owners[3].valid(),
           "Gaussian outside every allowed surface-distance range must remain unassigned");
    expect(assigned->assignedGaussians == 3 && assigned->unassignedGaussians == 1,
           "assignment statistics must exactly partition Gaussian primitive count");

    GaussianOwnershipAssignmentPolicy allRepresentations;
    allRepresentations.requireGaussianRepresentation = false;
    const auto relaxed =
        aether::world_gaussian::assignGaussianOwnership(asset, snapshot, allRepresentations);
    expect(relaxed.has_value(), "relaxed representation ownership assignment must remain valid");
    if (relaxed) {
        expect(relaxed->ownership.owners[2].value == 3,
               "with representation filtering disabled, specific mesh cabinet must beat room");
    }
}

void testStableIdBreaksExactGeometricTie() {
    WorldSnapshot snapshot;
    snapshot.timestamp = 100;
    snapshot.entities = {
        entity(9, "Later", "object", RepresentationKind::gaussian,
               Bounds{{-1.0F, -1.0F, -1.0F}, {1.0F, 1.0F, 1.0F}}),
        entity(5, "Earlier", "object", RepresentationKind::gaussian,
               Bounds{{-1.0F, -1.0F, -1.0F}, {1.0F, 1.0F, 1.0F}}),
    };
    GaussianAsset asset;
    asset.gaussians = {gaussian(0.0F, 0.0F, 0.0F)};

    const auto assigned = aether::world_gaussian::assignGaussianOwnership(asset, snapshot);
    expect(assigned.has_value(), "exact geometric tie fixture must assign ownership");
    if (assigned) {
        expect(assigned->ownership.owners.front().value == 5,
               "exact containment tie must deterministically choose lower stable entity ID");
    }
}

void testNearestSurfaceOwnershipOutsideBounds() {
    WorldSnapshot snapshot;
    snapshot.timestamp = 100;
    snapshot.entities = {
        entity(20, "Object", "object", RepresentationKind::gaussian,
               Bounds{{0.0F, 0.0F, 0.0F}, {1.0F, 1.0F, 1.0F}}),
    };
    GaussianAsset asset;
    asset.gaussians = {gaussian(1.08F, 0.5F, 0.5F), gaussian(1.20F, 0.5F, 0.5F)};

    GaussianOwnershipAssignmentPolicy policy;
    policy.maximumSurfaceDistanceMeters = 0.10F;
    const auto assigned = aether::world_gaussian::assignGaussianOwnership(asset, snapshot, policy);
    expect(assigned.has_value(), "near-surface ownership fixture must assign deterministically");
    if (!assigned)
        return;
    expect(assigned->ownership.owners[0].value == 20,
           "Gaussian just outside AABB but inside surface tolerance must attach to entity");
    expect(!assigned->ownership.owners[1].valid(),
           "Gaussian outside configured surface tolerance must remain unassigned");
}

void testCandidateBudgetFailsClosed() {
    WorldSnapshot snapshot;
    snapshot.timestamp = 100;
    snapshot.entities = {
        entity(30, "A", "dense", RepresentationKind::gaussian,
               Bounds{{-1.0F, -1.0F, -1.0F}, {1.0F, 1.0F, 1.0F}}),
        entity(31, "B", "dense", RepresentationKind::gaussian,
               Bounds{{-1.0F, -1.0F, -1.0F}, {1.0F, 1.0F, 1.0F}}),
    };
    GaussianAsset asset;
    asset.gaussians = {gaussian(0.0F, 0.0F, 0.0F), gaussian(0.1F, 0.0F, 0.0F)};

    GaussianOwnershipAssignmentPolicy policy;
    policy.maximumCandidatePairs = 1;
    const auto rejected = aether::world_gaussian::assignGaussianOwnership(asset, snapshot, policy);
    expect(!rejected.has_value(),
           "ownership assignment must fail closed when candidate-pair budget is exceeded");
}

} // namespace

int main() noexcept {
    try {
        testSpecificContainersAndRepresentationFiltering();
        testStableIdBreaksExactGeometricTie();
        testNearestSurfaceOwnershipOutsideBounds();
        testCandidateBudgetFailsClosed();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Gaussian ownership assignment tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
