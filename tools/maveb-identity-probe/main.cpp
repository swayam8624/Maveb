#include <aether/world/EntityAssociation.hpp>
#include <aether/world/WorldModel.hpp>

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {

using aether::world::Bounds;
using aether::world::EntityId;
using aether::world::EntityState;
using aether::world::PersistentWorldModel;
using aether::world::RepresentationKind;
using aether::world::WorldSnapshot;

EntityState entity(std::uint64_t id, std::string name, float x, std::uint64_t geometrySignature,
                   std::uint64_t appearanceSignature, std::uint64_t observedAt) {
    EntityState result;
    result.id = EntityId{id};
    result.name = std::move(name);
    result.semanticLabel = "object";
    result.transform.translation = {x, 0.0F, 0.0F};
    result.worldBounds =
        Bounds{{x - 0.10F, -0.10F, -0.10F}, {x + 0.10F, 0.10F, 0.10F}};
    result.representation = RepresentationKind::gaussian;
    result.geometrySignature = geometrySignature;
    result.appearanceSignature = appearanceSignature;
    result.lastObserved = observedAt;
    return result;
}

const EntityState* findByName(const WorldSnapshot& snapshot, std::string_view name) {
    for (const EntityState& state : snapshot.entities) {
        if (state.name == name)
            return &state;
    }
    return nullptr;
}

void emitCrossingProbe() {
    constexpr std::array<float, 5> separations{0.25F, 0.50F, 1.00F, 1.50F, 2.00F};
    constexpr std::array<float, 5> fractions{0.00F, 0.25F, 0.50F, 0.75F, 1.00F};

    std::cout << "\"crossing\":[";
    bool first = true;
    for (const bool distinctSignatures : {false, true}) {
        for (const bool reverseObservationOrder : {false, true}) {
            for (const float separation : separations) {
                WorldSnapshot previous;
                previous.revision = 1;
                previous.timestamp = 100;
                previous.entities = {
                    entity(1, "physical-a", 0.0F, distinctSignatures ? 101U : 1U,
                           distinctSignatures ? 201U : 1U, 100),
                    entity(2, "physical-b", separation, distinctSignatures ? 102U : 1U,
                           distinctSignatures ? 202U : 1U, 100),
                };

                for (const float fraction : fractions) {
                    const float displacement = separation * fraction;
                    std::vector<EntityState> observations{
                        entity(0, "physical-a", displacement, distinctSignatures ? 101U : 1U,
                               distinctSignatures ? 201U : 1U, 0),
                        entity(0, "physical-b", separation - displacement,
                               distinctSignatures ? 102U : 1U,
                               distinctSignatures ? 202U : 1U, 0),
                    };
                    if (reverseObservationOrder)
                        std::swap(observations[0], observations[1]);

                    auto associated =
                        aether::world::associateObservations(previous, 200, std::move(observations), 3);
                    if (!associated) {
                        std::cerr << associated.error().describe() << '\n';
                        std::exit(3);
                    }

                    const EntityState* physicalA = findByName(associated->snapshot, "physical-a");
                    const EntityState* physicalB = findByName(associated->snapshot, "physical-b");
                    const std::uint64_t predictedA = physicalA ? physicalA->id.value : 0;
                    const std::uint64_t predictedB = physicalB ? physicalB->id.value : 0;
                    const std::size_t correctlyPreserved =
                        static_cast<std::size_t>(predictedA == 1U) +
                        static_cast<std::size_t>(predictedB == 2U);
                    const std::size_t identitySwitches =
                        static_cast<std::size_t>(predictedA == 2U) +
                        static_cast<std::size_t>(predictedB == 1U);
                    const std::size_t falseBirths =
                        static_cast<std::size_t>(predictedA > 2U) +
                        static_cast<std::size_t>(predictedB > 2U);

                    if (!first)
                        std::cout << ',';
                    first = false;
                    std::cout << "{\"separationMeters\":" << separation
                              << ",\"travelFraction\":" << fraction
                              << ",\"distinctSignatures\":"
                              << (distinctSignatures ? "true" : "false")
                              << ",\"reverseObservationOrder\":"
                              << (reverseObservationOrder ? "true" : "false")
                              << ",\"predictedA\":" << predictedA
                              << ",\"predictedB\":" << predictedB
                              << ",\"identitySurvivalRate\":"
                              << static_cast<double>(correctlyPreserved) / 2.0
                              << ",\"identitySwitches\":" << identitySwitches
                              << ",\"falseBirths\":" << falseBirths << '}';
                }
            }
        }
    }
    std::cout << ']';
}

void emitReappearanceProbe(bool explicitIdentity) {
    PersistentWorldModel model;
    auto initial = model.ingest(
        100, {entity(0, "physical-a", 0.0F, 101, 201, 0),
              entity(0, "physical-b", 1.0F, 102, 202, 0)});
    if (!initial) {
        std::cerr << initial.error().describe() << '\n';
        std::exit(4);
    }

    const EntityState* initialB = findByName(*model.latest(), "physical-b");
    const std::uint64_t originalB = initialB ? initialB->id.value : 0;

    auto dropout = model.ingest(200, {entity(0, "physical-a", 0.02F, 101, 201, 0)});
    if (!dropout) {
        std::cerr << dropout.error().describe() << '\n';
        std::exit(5);
    }

    EntityState returningB = entity(explicitIdentity ? originalB : 0, "physical-b", 1.02F, 102, 202, 0);
    auto reappeared =
        model.ingest(300, {entity(0, "physical-a", 0.03F, 101, 201, 0), returningB});
    if (!reappeared) {
        std::cerr << reappeared.error().describe() << '\n';
        std::exit(6);
    }

    const EntityState* finalB = findByName(*model.latest(), "physical-b");
    const std::uint64_t finalId = finalB ? finalB->id.value : 0;
    std::cout << "{\"explicitIdentity\":" << (explicitIdentity ? "true" : "false")
              << ",\"originalId\":" << originalB << ",\"reappearedId\":" << finalId
              << ",\"identityPreserved\":" << (finalId == originalB ? "true" : "false")
              << ",\"dropoutRemovedCount\":" << dropout->diff.summary.removed
              << ",\"reappearanceAddedCount\":" << reappeared->diff.summary.added << '}';
}

int run() {
    std::cout << "{\"schemaVersion\":1,\"probe\":\"persistent-identity-baseline\",";
    emitCrossingProbe();
    std::cout << ",\"reappearance\":[";
    emitReappearanceProbe(false);
    std::cout << ',';
    emitReappearanceProbe(true);
    std::cout << "]}\n";
    return 0;
}

} // namespace

int main() noexcept {
    try {
        return run();
    } catch (const std::exception& error) {
        std::cerr << "Unhandled identity probe failure: " << error.what() << '\n';
    } catch (...) {
        std::cerr << "Unhandled identity probe failure\n";
    }
    return EXIT_FAILURE;
}
