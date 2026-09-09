#include <aether/world/EntityAssociation.hpp>

#include <cstdlib>
#include <exception>
#include <iostream>
#include <string>
#include <utility>

namespace {

using aether::world::Bounds;
using aether::world::EntityId;
using aether::world::EntityState;
using aether::world::RepresentationKind;
using aether::world::WorldSnapshot;

int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

EntityState entity(std::uint64_t id, std::string name, std::string semantic, float x,
                   std::uint64_t geometrySignature, std::uint64_t appearanceSignature,
                   std::uint64_t observedAt) {
    EntityState result;
    result.id = EntityId{id};
    result.name = std::move(name);
    result.semanticLabel = std::move(semantic);
    result.transform.translation = {x, 0.0F, 0.0F};
    result.worldBounds = Bounds{{x - 0.25F, -0.25F, -0.25F},
                                {x + 0.25F, 0.25F, 0.25F}};
    result.representation = RepresentationKind::hybrid;
    result.geometrySignature = geometrySignature;
    result.appearanceSignature = appearanceSignature;
    result.lastObserved = observedAt;
    return result;
}

const EntityState* findByName(const WorldSnapshot& snapshot, const std::string& name) {
    for (const EntityState& state : snapshot.entities) {
        if (state.name == name)
            return &state;
    }
    return nullptr;
}

void testStableAssociationAndNewIdentity() {
    WorldSnapshot previous;
    previous.revision = 7;
    previous.timestamp = 100;
    previous.entities = {
        entity(1, "Wall", "wall", 0.0F, 10, 20, 100),
        entity(2, "Chair", "chair", 1.0F, 30, 40, 100),
    };

    std::vector<EntityState> observations = {
        entity(0, "Wall", "wall", 0.02F, 10, 20, 0),
        entity(0, "Chair", "chair", 1.25F, 30, 40, 0),
        entity(0, "Plant", "plant", 5.0F, 50, 60, 0),
    };

    const auto associated =
        aether::world::associateObservations(previous, 200, std::move(observations), 100);
    expect(associated.has_value(), "unassigned observations must associate against prior world state");
    if (!associated)
        return;

    expect(associated->reusedIds == 2, "wall and chair must retain their persistent IDs");
    expect(associated->createdIds == 1, "new plant must receive exactly one fresh ID");
    expect(associated->missingPreviousEntities == 0,
           "both prior entities must be accounted for by the new observation");
    expect(associated->nextEntityId == 101, "allocator must advance past the newly assigned ID");

    const EntityState* wall = findByName(associated->snapshot, "Wall");
    const EntityState* chair = findByName(associated->snapshot, "Chair");
    const EntityState* plant = findByName(associated->snapshot, "Plant");
    expect(wall && wall->id.value == 1, "wall must preserve stable ID 1");
    expect(chair && chair->id.value == 2, "chair must preserve stable ID 2");
    expect(plant && plant->id.value == 100, "new plant must receive allocator ID 100");
    expect(wall && wall->lastObserved == 200, "association must stamp missing observation time");
    expect(chair && chair->lastObserved == 200, "association must stamp all reused observations");

    const auto diff = aether::world::diffSnapshots(previous, associated->snapshot);
    expect(diff.has_value(), "associated observation must remain directly diffable");
    if (diff) {
        expect(diff->summary.added == 1, "new plant must appear as one added entity");
        expect(diff->summary.removed == 0,
               "stable matching must prevent false remove/add churn for existing objects");
    }
}

void testSemanticMismatchDoesNotStealIdentity() {
    WorldSnapshot previous;
    previous.timestamp = 100;
    previous.entities = {entity(11, "Chair", "chair", 0.0F, 1, 1, 100)};

    std::vector<EntityState> observations = {
        entity(0, "Lamp", "lamp", 0.02F, 1, 1, 0),
    };

    const auto associated =
        aether::world::associateObservations(previous, 200, std::move(observations), 20);
    expect(associated.has_value(), "semantic mismatch fixture must remain valid");
    if (!associated)
        return;

    const EntityState* lamp = findByName(associated->snapshot, "Lamp");
    expect(lamp && lamp->id.value == 20,
           "nearby object with conflicting semantics must receive a new persistent ID");
    expect(associated->reusedIds == 0, "semantic mismatch must not reuse prior identity by default");
    expect(associated->createdIds == 1, "semantic mismatch must allocate one new identity");
    expect(associated->missingPreviousEntities == 1,
           "unobserved chair must remain missing rather than being relabeled as a lamp");
}

void testExplicitIdentityIsAuthoritative() {
    WorldSnapshot previous;
    previous.timestamp = 100;
    previous.entities = {entity(42, "Known", "object", 0.0F, 1, 1, 100)};

    std::vector<EntityState> observations = {
        entity(42, "Known", "different-label", 9.0F, 99, 99, 200),
    };

    const auto associated =
        aether::world::associateObservations(previous, 200, std::move(observations), 100);
    expect(associated.has_value(), "authoritative explicit identity must be accepted");
    if (!associated)
        return;
    expect(associated->snapshot.entities.front().id.value == 42,
           "explicit upstream stable ID must never be reassigned by heuristic association");
    expect(associated->reusedIds == 1, "explicit prior identity must count as reused");
}

} // namespace

int main() noexcept {
    try {
        testStableAssociationAndNewIdentity();
        testSemanticMismatchDoesNotStealIdentity();
        testExplicitIdentityIsAuthoritative();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Entity association tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
